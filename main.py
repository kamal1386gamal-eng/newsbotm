import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# تنظیمات اولیه
logging.basicConfig(level=logging.INFO)

# ========================
# دریافت تنظیمات از Environment Variables
# ========================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است!")

# شناسه کانال مقصد
CHANNEL_ID = "@spark_news_tel"

# ========================
# تعریف حالت‌های مکالمه (FSM)
# ========================
class Form(StatesGroup):
    waiting_for_photo = State()
    showing_preview = State()
    waiting_for_caption = State()

# ========================
# راه‌اندازی ربات و دیسپچر
# ========================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)


# ========================
# هندلرها
# ========================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_photo)
    await message.answer(
        "سلام! 👋\n"
        "یک عکس بفرستید تا پس از تأیید و ویرایش، در کانال منتشر شود.\n"
        "برای لغو، /cancel را بزنید."
    )


@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")


@dp.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    """دریافت عکس و نمایش پیش‌نمایش"""
    photo = message.photo[-1]
    file_id = photo.file_id
    caption = message.caption or ""

    await state.update_data(
        photo_file_id=file_id,
        caption=caption,
    )

    # ارسال پیش‌نمایش با دکمه‌ها
    preview_message = await message.answer_photo(
        photo=file_id,
        caption=f"📸 **پیش‌نمایش پست**\n\n{caption if caption else '(بدون کپشن)'}",
        reply_markup=preview_keyboard(),
    )

    await state.update_data(
        preview_chat_id=preview_message.chat.id,
        preview_message_id=preview_message.message_id,
    )
    await state.set_state(Form.showing_preview)


@dp.callback_query(F.data.in_(["post", "cancel_post", "edit_caption"]), StateFilter(Form.showing_preview))
async def process_preview_actions(callback: types.CallbackQuery, state: FSMContext):
    """پردازش دکمه‌های پیش‌نمایش"""
    await callback.answer()

    user_data = await state.get_data()
    if not user_data:
        await callback.message.answer("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره عکس را بفرستید.")
        await state.clear()
        return

    if callback.data == "post":
        # ===== ارسال به کانال =====
        try:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=user_data["photo_file_id"],
                caption=user_data["caption"] if user_data["caption"] else None,
            )
            # ویرایش کپشن پیام پیش‌نمایش به جای edit_text
            await bot.edit_message_caption(
                chat_id=user_data["preview_chat_id"],
                message_id=user_data["preview_message_id"],
                caption="✅ **عکس با موفقیت در کانال منتشر شد.**",
                reply_markup=None,  # حذف دکمه‌ها
            )
        except Exception as e:
            logging.error(f"خطا در ارسال به کانال: {e}")
            await callback.message.answer(
                "❌ خطا در انتشار عکس. مطمئن شوید ربات در کانال ادمین است."
            )
        await state.clear()

    elif callback.data == "cancel_post":
        # ===== لغو =====
        await bot.edit_message_caption(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"],
            caption="❌ **انتشار لغو شد.**",
            reply_markup=None,
        )
        await state.clear()

    elif callback.data == "edit_caption":
        # ===== ویرایش کپشن =====
        # ارسال یک پیام جدید برای دریافت کپشن (نه ادیت کردن پیام عکس)
        await callback.message.answer(
            f"✏️ کپشن جدید را به‌صورت متن ارسال کنید.\n"
            f"کپشن فعلی: {user_data['caption'] if user_data['caption'] else '(بدون کپشن)'}"
        )
        await state.set_state(Form.waiting_for_caption)


@dp.message(StateFilter(Form.waiting_for_caption), F.text)
async def handle_new_caption(message: types.Message, state: FSMContext):
    """دریافت کپشن جدید و به‌روزرسانی پیش‌نمایش"""
    new_caption = message.text
    user_data = await state.get_data()

    if not user_data:
        await message.answer("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره عکس را بفرستید.")
        await state.clear()
        return

    # به‌روزرسانی کپشن
    await state.update_data(caption=new_caption)

    # ویرایش کپشن پیام پیش‌نمایش
    try:
        await bot.edit_message_caption(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"],
            caption=f"📸 **پیش‌نمایش پست**\n\n{new_caption if new_caption else '(بدون کپشن)'}",
            reply_markup=preview_keyboard(),  # دکمه‌ها دوباره نمایش داده می‌شوند
        )
        await message.answer("✅ کپشن به‌روزرسانی شد. پیش‌نمایش جدید را ببینید.")
    except Exception as e:
        logging.error(f"خطا در ادیت: {e}")
        await message.answer("❌ خطا در به‌روزرسانی پیش‌نمایش.")

    await state.set_state(Form.showing_preview)


@dp.message(StateFilter(Form.waiting_for_caption))
async def invalid_caption_input(message: types.Message):
    await message.answer("❌ لطفاً کپشن را به‌صورت متن ارسال کنید.")


@dp.message()
async def other_messages(message: types.Message):
    await message.answer("❌ فقط عکس بفرستید. برای راهنمایی /start را بزنید.")


# ========================
# صفحه‌کلید دکمه‌ها
# ========================
def preview_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ پست کردن", callback_data="post"),
        types.InlineKeyboardButton(text="✏️ ویرایش کپشن", callback_data="edit_caption"),
        types.InlineKeyboardButton(text="❌ لغو", callback_data="cancel_post"),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


# ========================
# اجرا
# ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
