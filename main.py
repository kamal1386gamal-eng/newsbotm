import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# تنظیمات اولیه
logging.basicConfig(level=logging.INFO)

# ========================
# دریافت تنظیمات از Environment Variables
# ========================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است!")

CHANNEL_ID = "@spark_news_tel"  # شناسه کانال مقصد

# ========================
# تعریف حالت‌های مکالمه (FSM)
# ========================
class Form(StatesGroup):
    waiting_for_photo = State()

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
    """فرمان /start"""
    await state.set_state(Form.waiting_for_photo)
    await message.answer(
        "سلام! 👋\n"
        "یک عکس را برای من بفرستید تا پس از تأیید شما، آن را در کانال منتشر کنم.\n"
        "برای لغو در هر مرحله، دستور /cancel را بفرستید."
    )


@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    """لغو عملیات"""
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")


@dp.message(Form.waiting_for_photo, F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    """دریافت عکس و درخواست تأیید"""
    # ذخیره اطلاعات عکس در state
    await state.update_data(
        chat_id=message.chat.id,
        message_id=message.message_id
    )

    # ساخت دکمه‌های تأیید
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="✅ بله، منتشر کن",
        callback_data="confirm"
    ))
    builder.add(types.InlineKeyboardButton(
        text="❌ نه، لغو کن",
        callback_data="cancel"
    ))

    await message.answer(
        "آیا این عکس را در کانال منتشر کنم؟",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.in_(["confirm", "cancel"]))
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    """پردازش دکمه‌های تأیید/لغو"""
    await callback.answer()

    if callback.data == "confirm":
        # دریافت اطلاعات عکس ذخیره شده
        user_data = await state.get_data()
        if not user_data:
            await callback.message.edit_text("متأسفم، داده‌ای برای انتشار پیدا نشد. لطفاً دوباره عکس را بفرستید.")
            await state.clear()
            return

        try:
            # فوروارد کردن عکس به کانال
            await bot.forward_message(
                chat_id=CHANNEL_ID,
                from_chat_id=user_data["chat_id"],
                message_id=user_data["message_id"],
            )
            await callback.message.edit_text("✅ عکس با موفقیت در کانال منتشر شد.")
        except Exception as e:
            logging.error(f"خطا در ارسال به کانال: {e}")
            await callback.message.edit_text(
                "❌ خطا در انتشار عکس. مطمئن شوید که ربات در کانال ادمین است و شناسه کانال صحیح است."
            )
    else:  # cancel
        await callback.message.edit_text("❌ انتشار لغو شد.")

    # پاک کردن state کاربر
    await state.clear()


@dp.message(Form.waiting_for_photo)
async def handle_invalid_input(message: types.Message):
    """دریافت پیام غیرمنتظره در حالت انتظار عکس"""
    await message.answer(
        "لطفاً یک عکس بفرستید یا برای لغو، /cancel را بزنید."
    )


# ========================
# اجرای ربات
# ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
