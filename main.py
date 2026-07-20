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
    waiting_for_photo = State()       # منتظر دریافت عکس
    showing_preview = State()          # نمایش پیش‌نمایش (منتظر انتخاب دکمه)
    waiting_for_caption = State()      # منتظر دریافت کپشن جدید برای ویرایش

# ========================
# راه‌اندازی ربات و دیسپچر
# ========================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)


# ========================
# هندلرهای مربوط به مکالمه
# ========================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """فرمان /start - راهنمایی اولیه"""
    await state.set_state(Form.waiting_for_photo)
    await message.answer(
        "سلام! 👋\n"
        "یک عکس را برای من بفرستید تا پس از تأیید و ویرایش (در صورت نیاز)، آن را در کانال منتشر کنم.\n"
        "برای لغو در هر مرحله، دستور /cancel را بفرستید.\n\n"
        "⚠️ نیازی به زدن /start نیست! مستقیماً عکس بفرستید."
    )


@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    """لغو عملیات"""
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")


@dp.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    """دریافت عکس و نمایش پیش‌نمایش"""
    # دریافت اطلاعات عکس
    photo = message.photo[-1]  # بهترین کیفیت
    file_id = photo.file_id
    caption = message.caption or ""

    # ذخیره اطلاعات در state
    await state.update_data(
        photo_file_id=file_id,
        caption=caption,
        original_chat_id=message.chat.id,
        original_message_id=message.message_id,
    )

    # ارسال پیش‌نمایش به کاربر
    preview_message = await message.answer_photo(
        photo=file_id,
        caption=f"📸 **پیش‌نمایش پست**\n\n{caption if caption else '(بدون کپشن)'}",
        reply_markup=preview_keyboard(),
    )

    # ذخیره شناسه پیام پیش‌نمایش برای ادیت بعدی
    await state.update_data(
        preview_chat_id=preview_message.chat.id,
        preview_message_id=preview_message.message_id,
    )

    # تغییر حالت به نمایش پیش‌نمایش
    await state.set_state(Form.showing_preview)


@dp.callback_query(F.data.in_(["post", "cancel_post", "edit_caption"]), StateFilter(Form.showing_preview))
async def process_preview_actions(callback: types.CallbackQuery, state: FSMContext):
    """پردازش دکمه‌های موجود در پیش‌نمایش"""
    await callback.answer()

    user_data = await state.get_data()
    if not user_data:
        await callback.message.edit_text("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره عکس را بفرستید.")
        await state.clear()
        return

    if callback.data == "post":
        # ========== پست کردن در کانال ==========
        try:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=user_data["photo_file_id"],
                caption=user_data["caption"] if user_data["caption"] else None,
            )
            await callback.message.edit_text("✅ عکس با موفقیت در کانال منتشر شد.")
        except Exception as e:
            logging.error(f"خطا در ارسال به کانال: {e}")
            await callback.message.edit_text(
                "❌ خطا در انتشار عکس. مطمئن شوید که ربات در کانال ادمین است و شناسه کانال صحیح است."
            )
        await state.clear()

    elif callback.data == "cancel_post":
        # ========== لغو انتشار ==========
        await callback.message.edit_text("❌ انتشار لغو شد.")
        await state.clear()

    elif callback.data == "edit_caption":
        # ========== ویرایش کپشن ==========
        await callback.message.edit_text(
            "✏️ لطفاً کپشن جدید را به‌صورت یک پیام متنی ارسال کنید.\n"
            f"کپشن فعلی: {user_data['caption'] if user_data['caption'] else '(بدون کپشن)'}"
        )
        await state.set_state(Form.waiting_for_caption)


@dp.message(StateFilter(Form.waiting_for_caption), F.text)
async def handle_new_caption(message: types.Message, state: FSMContext):
    """دریافت کپشن جدید از کاربر و به‌روزرسانی پیش‌نمایش"""
    new_caption = message.text

    # دریافت داده‌های قبلی
    user_data = await state.get_data()
    if not user_data:
        await message.answer("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره عکس را بفرستید.")
        await state.clear()
        return

    # به‌روزرسانی کپشن در state
    await state.update_data(caption=new_caption)

    # ادیت کردن پیام پیش‌نمایش با کپشن جدید
    try:
        await bot.edit_message_caption(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"],
            caption=f"📸 **پیش‌نمایش پست**\n\n{new_caption if new_caption else '(بدون کپشن)'}",
            reply_markup=preview_keyboard(),
        )
        await message.answer("✅ کپشن با موفقیت به‌روزرسانی شد. پیش‌نمایش جدید را مشاهده کنید.")
    except Exception as e:
        logging.error(f"خطا در ادیت پیام: {e}")
        await message.answer("❌ خطا در به‌روزرسانی پیش‌نمایش. لطفاً دوباره تلاش کنید.")

    # بازگشت به حالت نمایش پیش‌نمایش
    await state.set_state(Form.showing_preview)


@dp.message(StateFilter(Form.waiting_for_caption))
async def handle_invalid_caption_input(message: types.Message):
    """دریافت پیام غیرمتن در حالت انتظار کپشن"""
    await message.answer("❌ لطفاً کپشن جدید را به‌صورت یک پیام متنی ارسال کنید.")


@dp.message()
async def handle_other_messages(message: types.Message):
    """دریافت پیام‌های غیرعکس"""
    await message.answer(
        "❌ لطفاً فقط یک عکس بفرستید.\n"
        "برای راهنمایی، /start را بزنید."
    )


# ========================
# توابع کمکی
# ========================

def preview_keyboard():
    """ساخت صفحه‌کلید دکمه‌های پیش‌نمایش"""
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ پست کردن", callback_data="post"),
        types.InlineKeyboardButton(text="✏️ ویرایش کپشن", callback_data="edit_caption"),
        types.InlineKeyboardButton(text="❌ لغو", callback_data="cancel_post"),
    )
    builder.adjust(2, 1)  # دو دکمه در ردیف اول، یک دکمه در ردیف دوم
    return builder.as_markup()


# ========================
# اجرای ربات
# ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
