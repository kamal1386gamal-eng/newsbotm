import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any, Optional

# تنظیمات اولیه
logging.basicConfig(level=logging.INFO)

# ========================
# دریافت تنظیمات از Environment Variables
# ========================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است!")

CHANNEL_ID = os.getenv("CHANNEL_ID", "@spark_news_tel")  # کانال پیش‌فرض

# ========================
# تعریف حالت‌های مکالمه (FSM)
# ========================
class Form(StatesGroup):
    waiting_for_media = State()
    showing_preview = State()
    waiting_for_caption = State()

# ========================
# راه‌اندازی ربات و دیسپچر
# ========================
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)


# ========================
# توابع کمکی
# ========================

def get_media_type(message: types.Message) -> str:
    if message.photo:
        return "photo"
    elif message.video:
        return "video"
    elif message.audio:
        return "audio"
    elif message.document:
        return "document"
    elif message.voice:
        return "voice"
    elif message.video_note:
        return "video_note"
    elif message.text:
        return "text"
    else:
        return "unknown"

def extract_media_from_message(message: types.Message) -> Dict[str, Any]:
    media_data = {"type": get_media_type(message), "caption": message.caption or ""}

    if message.photo:
        media_data["file_id"] = message.photo[-1].file_id
    elif message.video:
        media_data["file_id"] = message.video.file_id
        media_data["duration"] = message.video.duration
        media_data["width"] = message.video.width
        media_data["height"] = message.video.height
    elif message.audio:
        media_data["file_id"] = message.audio.file_id
        media_data["duration"] = message.audio.duration
        media_data["performer"] = message.audio.performer
        media_data["title"] = message.audio.title
    elif message.document:
        media_data["file_id"] = message.document.file_id
        media_data["file_name"] = message.document.file_name
    elif message.voice:
        media_data["file_id"] = message.voice.file_id
        media_data["duration"] = message.voice.duration
    elif message.video_note:
        media_data["file_id"] = message.video_note.file_id
        media_data["duration"] = message.video_note.duration
        media_data["length"] = message.video_note.length
    elif message.text:
        media_data["text"] = message.text

    return media_data

async def send_preview(
    target_message: types.Message,
    media_type: str,
    media_data: Dict[str, Any],
    caption: str,
) -> Dict[str, Any]:
    """
    ارسال پیش‌نمایش و برگرداندن دیکشنری شامل شناسه‌های پیام(ها)
    برای مدیاهای معمولی یک پیام، برای video_note دو پیام (video_note + متن)
    """
    caption_text = caption if caption else '(بدون کپشن)'
    full_caption = f"📸 **پیش‌نمایش پست**\n\n{caption_text}"

    result = {"main_chat_id": target_message.chat.id, "main_message_id": None, "extra_message_id": None}

    if media_type == "photo":
        msg = await target_message.answer_photo(
            photo=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    elif media_type == "video":
        msg = await target_message.answer_video(
            video=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    elif media_type == "audio":
        msg = await target_message.answer_audio(
            audio=media_data["file_id"],
            caption=full_caption,
            performer=media_data.get("performer"),
            title=media_data.get("title"),
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    elif media_type == "document":
        msg = await target_message.answer_document(
            document=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    elif media_type == "voice":
        msg = await target_message.answer_voice(
            voice=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    elif media_type == "video_note":
        # خود ویدیو نوت (بدون کپشن)
        vn_msg = await target_message.answer_video_note(
            video_note=media_data["file_id"]
        )
        # پیام متنی جداگانه برای کپشن و دکمه‌ها
        txt_msg = await target_message.answer(
            full_caption,
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = vn_msg.message_id      # برای حذف (اختیاری)
        result["extra_message_id"] = txt_msg.message_id     # این یکی کپشن و دکمه‌ها رو داره
    elif media_type == "text":
        # برای پست متنی، کپشن جدید جایگزین متن اصلی می‌شود
        msg = await target_message.answer(
            f"📝 **پیش‌نمایش پست**\n\n{caption_text}",
            reply_markup=preview_keyboard(),
            parse_mode="Markdown"
        )
        result["main_message_id"] = msg.message_id
    else:
        msg = await target_message.answer("❌ نوع فایل پشتیبانی نمی‌شود.")
        result["main_message_id"] = msg.message_id

    return result

async def delete_preview_messages(chat_id: int, main_msg_id: Optional[int], extra_msg_id: Optional[int] = None):
    """حذف پیام‌های پیش‌نمایش (اصلی + اضافی در صورت وجود)"""
    if main_msg_id:
        try:
            await bot.delete_message(chat_id, main_msg_id)
        except Exception as e:
            logging.warning(f"Could not delete main preview: {e}")
    if extra_msg_id:
        try:
            await bot.delete_message(chat_id, extra_msg_id)
        except Exception as e:
            logging.warning(f"Could not delete extra preview: {e}")

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
# هندلرها
# ========================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_media)
    await message.answer(
        "سلام! 👋\n"
        "هر نوع محتوایی (عکس، ویدیو، موسیقی، متن، فایل) بفرستید.\n"
        "پس از تأیید و ویرایش، در کانال منتشر می‌شود.\n"
        "برای لغو، /cancel را بزنید."
    )

@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        # اگر پیش‌نمایشی موجود بود، پاکش کن
        data = await state.get_data()
        preview_main = data.get("preview_main_message_id")
        preview_extra = data.get("preview_extra_message_id")
        chat_id = data.get("preview_chat_id")
        if chat_id and preview_main:
            await delete_preview_messages(chat_id, preview_main, preview_extra)
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")

@dp.message(StateFilter(Form.waiting_for_media), F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text)
async def handle_media(message: types.Message, state: FSMContext):
    media_type = get_media_type(message)
    media_data = extract_media_from_message(message)
    caption = message.caption or ""
    # برای متن، caption همان متن است (کپشن جداگانه نداریم)
    if media_type == "text":
        caption = media_data.get("text", "")

    # ذخیره اطلاعات
    await state.update_data(
        media_type=media_type,
        media_data=media_data,
        caption=caption,
    )

    # ارسال پیش‌نمایش
    preview_info = await send_preview(message, media_type, media_data, caption)

    # ذخیره شناسه‌های پیام‌ها
    await state.update_data(
        preview_chat_id=preview_info["main_chat_id"],
        preview_main_message_id=preview_info["main_message_id"],
        preview_extra_message_id=preview_info.get("extra_message_id"),
        # برای ویدیو نوت، دکمه‌ها و کپشن در extra_message هستند
        # در edit_caption باید همون extra_message رو ویرایش کنیم
    )
    await state.set_state(Form.showing_preview)

@dp.callback_query(F.data.in_(["post", "cancel_post", "edit_caption"]), StateFilter(Form.showing_preview))
async def process_preview_actions(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_data = await state.get_data()
    if not user_data:
        await callback.message.answer("داده‌ای یافت نشد. دوباره محتوا را بفرستید.")
        await state.clear()
        return

    if callback.data == "post":
        await send_to_channel(callback, user_data)
        await state.clear()

    elif callback.data == "cancel_post":
        await cancel_post(callback, user_data)
        await state.clear()

    elif callback.data == "edit_caption":
        current_caption = user_data.get("caption", "")
        await callback.message.answer(
            f"✏️ **کپشن جدید** را به‌صورت یک پیام متنی ارسال کنید.\n"
            f"کپشن فعلی: {current_caption or '(بدون کپشن)'}"
        )
        await state.set_state(Form.waiting_for_caption)

@dp.message(StateFilter(Form.waiting_for_caption), F.text)
async def handle_new_caption(message: types.Message, state: FSMContext):
    new_caption = message.text
    user_data = await state.get_data()
    if not user_data:
        await message.answer("داده‌ای یافت نشد. دوباره محتوا را بفرستید.")
        await state.clear()
        return

    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    chat_id = user_data["preview_chat_id"]
    main_msg_id = user_data.get("preview_main_message_id")
    extra_msg_id = user_data.get("preview_extra_message_id")  # برای video_note

    # آماده‌سازی کپشن جدید
    caption_text = new_caption if new_caption else '(بدون کپشن)'
    full_caption = f"📸 **پیش‌نمایش پست**\n\n{caption_text}"

    # اگر از edit_message_caption پشتیبانی می‌کند (photo, video, audio, document)
    if media_type in ("photo", "video", "audio", "document"):
        # پیام اصلی همون عکس/ویدیو هست و قابل ویرایش
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=main_msg_id,
                caption=full_caption,
                reply_markup=preview_keyboard(),
                parse_mode="Markdown"
            )
            await state.update_data(caption=new_caption)
            await message.answer("✅ کپشن با موفقیت ویرایش شد.")
            await state.set_state(Form.showing_preview)
            return
        except Exception as e:
            logging.warning(f"edit_message_caption failed: {e}. Trying fallback.")

    # برای voice (پشتیبانی از ویرایش کپشن ندارد ولی تلاش می‌کنیم، در غیر این صورت fallback)
    if media_type == "voice":
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=main_msg_id,
                caption=full_caption,
                reply_markup=preview_keyboard(),
                parse_mode="Markdown"
            )
            await state.update_data(caption=new_caption)
            await message.answer("✅ کپشن با موفقیت ویرایش شد.")
            await state.set_state(Form.showing_preview)
            return
        except Exception:
            pass  # fallback

    # fallback: حذف پیش‌نمایش قبلی و ساخت جدید
    # (برای video_note و voice که ویرایش نشد و متن)
    await delete_preview_messages(chat_id, main_msg_id, extra_msg_id)

    # برای متن، چون محتوای اصلی همون کپشنه، باید media_data رو به‌روز کنیم
    if media_type == "text":
        media_data["text"] = new_caption  # خود متن جدید میشه

    # ارسال پیش‌نمایش جدید
    new_info = await send_preview(message, media_type, media_data, new_caption)

    await state.update_data(
        caption=new_caption,
        preview_chat_id=new_info["main_chat_id"],
        preview_main_message_id=new_info["main_message_id"],
        preview_extra_message_id=new_info.get("extra_message_id"),
        media_data=media_data,
    )
    await message.answer("✅ کپشن با موفقیت ویرایش شد. پیش‌نمایش جدید را ببینید.")
    await state.set_state(Form.showing_preview)

@dp.message(StateFilter(Form.waiting_for_caption))
async def invalid_caption_input(message: types.Message):
    await message.answer("❌ لطفاً کپشن را به‌صورت یک پیام **متن** ارسال کنید.")

@dp.message(StateFilter(Form.waiting_for_media), ~F.text)
async def non_media_in_waiting(message: types.Message):
    """اگر کاربر چیزی غیر از محتوای قابل قبول فرستاد"""
    await message.answer("❌ فقط محتوای معتبر (عکس، ویدیو، موسیقی، فایل، ویس، ویدیو نوت، متن) بفرستید.")

@dp.message()
async def other_messages(message: types.Message):
    await message.answer(
        "❌ الان در حالتی نیستم که بتونم این پیام رو پردازش کنم.\n"
        "برای شروع دوباره /start بزنید."
    )

# ========================
# توابع ارسال به کانال و لغو
# ========================

async def send_to_channel(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    caption = user_data.get("caption", "")
    chat_id = user_data["preview_chat_id"]
    main_msg_id = user_data.get("preview_main_message_id")
    extra_msg_id = user_data.get("preview_extra_message_id")

    try:
        if media_type == "photo":
            await bot.send_photo(CHANNEL_ID, media_data["file_id"], caption=caption or None, parse_mode="Markdown")
        elif media_type == "video":
            await bot.send_video(CHANNEL_ID, media_data["file_id"], caption=caption or None, parse_mode="Markdown")
        elif media_type == "audio":
            await bot.send_audio(CHANNEL_ID, media_data["file_id"], caption=caption or None,
                                 performer=media_data.get("performer"), title=media_data.get("title"),
                                 parse_mode="Markdown")
        elif media_type == "document":
            await bot.send_document(CHANNEL_ID, media_data["file_id"], caption=caption or None, parse_mode="Markdown")
        elif media_type == "voice":
            await bot.send_voice(CHANNEL_ID, media_data["file_id"], caption=caption or None, parse_mode="Markdown")
        elif media_type == "video_note":
            await bot.send_video_note(CHANNEL_ID, media_data["file_id"])
            if caption:
                await bot.send_message(CHANNEL_ID, caption, parse_mode="Markdown")
        elif media_type == "text":
            await bot.send_message(CHANNEL_ID, media_data.get("text", ""), parse_mode="Markdown")

        # حذف پیش‌نمایش بعد از انتشار موفق
        await delete_preview_messages(chat_id, main_msg_id, extra_msg_id)

        # اطلاع‌رسانی به کاربر
        await callback.message.answer("✅ **محتوا با موفقیت در کانال منتشر شد.**")
    except Exception as e:
        logging.error(f"خطا در ارسال به کانال: {e}")
        await callback.message.answer("❌ خطا در انتشار. مطمئن شوید ربات در کانال ادمین است.")

async def cancel_post(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    chat_id = user_data["preview_chat_id"]
    main_msg_id = user_data.get("preview_main_message_id")
    extra_msg_id = user_data.get("preview_extra_message_id")
    await delete_preview_messages(chat_id, main_msg_id, extra_msg_id)
    await callback.message.answer("❌ **انتشار لغو شد.**")

# ========================
# اجرا
# ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
