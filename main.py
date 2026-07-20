import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any

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


async def send_preview_message(target_message: types.Message, media_type: str, media_data: Dict[str, Any], caption: str) -> types.Message:
    """ارسال یک پیام پیش‌نمایش با دکمه‌ها"""
    caption_text = caption if caption else '(بدون کپشن)'
    full_caption = f"📸 **پیش‌نمایش پست**\n\n{caption_text}"
    
    if media_type == "photo":
        return await target_message.answer_photo(
            photo=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "video":
        return await target_message.answer_video(
            video=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "audio":
        return await target_message.answer_audio(
            audio=media_data["file_id"],
            caption=full_caption,
            performer=media_data.get("performer"),
            title=media_data.get("title"),
            reply_markup=preview_keyboard()
        )
    elif media_type == "document":
        return await target_message.answer_document(
            document=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "voice":
        return await target_message.answer_voice(
            voice=media_data["file_id"],
            caption=full_caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "video_note":
        # ویدیو نوتی کپشن ندارد، فقط خود ویدیو را نمایش می‌دهیم و سپس یک پیام متنی با کپشن جداگانه می‌فرستیم
        video_msg = await target_message.answer_video_note(
            video_note=media_data["file_id"],
            reply_markup=None
        )
        # برای ویدیو نوتی، کپشن را به‌صورت یک پیام متنی جداگانه با دکمه‌ها می‌فرستیم
        caption_msg = await target_message.answer(
            full_caption,
            reply_markup=preview_keyboard()
        )
        # ترکیب دو پیام در یک شیء برای ذخیره‌سازی (فقط آخرین پیام را برمی‌گردانیم)
        return caption_msg
    elif media_type == "text":
        return await target_message.answer(
            f"📝 **پیش‌نمایش پست**\n\n{media_data.get('text', '')}",
            reply_markup=preview_keyboard()
        )
    else:
        return await target_message.answer("❌ نوع فایل پشتیبانی نمی‌شود.")


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
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")


@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text)
async def handle_media(message: types.Message, state: FSMContext):
    media_type = get_media_type(message)
    media_data = extract_media_from_message(message)
    caption = message.caption or ""

    # ذخیره در state
    await state.update_data(
        media_type=media_type,
        media_data=media_data,
        caption=caption,
    )

    # ارسال پیش‌نمایش
    preview_msg = await send_preview_message(message, media_type, media_data, caption)
    
    # ذخیره شناسه پیام پیش‌نمایش
    await state.update_data(
        preview_chat_id=preview_msg.chat.id,
        preview_message_id=preview_msg.message_id,
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
        await callback.message.answer(
            f"✏️ **کپشن جدید** را به‌صورت یک پیام متنی ارسال کنید.\n"
            f"کپشن فعلی: {user_data.get('caption', '') or '(بدون کپشن)'}"
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

    # به‌روزرسانی کپشن در state
    await state.update_data(caption=new_caption)

    # ===== حذف پیام پیش‌نمایش قبلی =====
    try:
        await bot.delete_message(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"]
        )
    except Exception as e:
        logging.warning(f"Could not delete old preview: {e}")

    # ===== ارسال پیش‌نمایش جدید با همان فایل و کپشن جدید =====
    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    
    # ارسال پیام جدید با همان فایل و کپشن جدید
    new_preview = await send_preview_message(message, media_type, media_data, new_caption)
    
    # به‌روزرسانی شناسه پیام پیش‌نمایش در state
    await state.update_data(
        preview_chat_id=new_preview.chat.id,
        preview_message_id=new_preview.message_id,
    )

    await message.answer("✅ کپشن به‌روزرسانی شد. پیش‌نمایش جدید را مشاهده کنید.")
    await state.set_state(Form.showing_preview)


@dp.message(StateFilter(Form.waiting_for_caption))
async def invalid_caption_input(message: types.Message):
    await message.answer("❌ لطفاً کپشن را به‌صورت یک پیام **متن** ارسال کنید.")


@dp.message()
async def other_messages(message: types.Message):
    await message.answer(
        "❌ فقط محتوای معتبر بفرستید (عکس، ویدیو، موسیقی، فایل، متن).\n"
        "برای راهنمایی /start را بزنید."
    )


# ========================
# توابع ارسال به کانال و لغو
# ========================

async def send_to_channel(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    caption = user_data.get("caption", "")
    
    try:
        if media_type == "photo":
            await bot.send_photo(CHANNEL_ID, media_data["file_id"], caption=caption if caption else None)
        elif media_type == "video":
            await bot.send_video(CHANNEL_ID, media_data["file_id"], caption=caption if caption else None)
        elif media_type == "audio":
            await bot.send_audio(CHANNEL_ID, media_data["file_id"], caption=caption if caption else None,
                                 performer=media_data.get("performer"), title=media_data.get("title"))
        elif media_type == "document":
            await bot.send_document(CHANNEL_ID, media_data["file_id"], caption=caption if caption else None)
        elif media_type == "voice":
            await bot.send_voice(CHANNEL_ID, media_data["file_id"], caption=caption if caption else None)
        elif media_type == "video_note":
            await bot.send_video_note(CHANNEL_ID, media_data["file_id"])
            # برای ویدیو نوتی، کپشن را جداگانه می‌فرستیم
            if caption:
                await bot.send_message(CHANNEL_ID, caption)
        elif media_type == "text":
            await bot.send_message(CHANNEL_ID, media_data.get("text", ""))
        
        # به‌روزرسانی پیام پیش‌نمایش
        try:
            await bot.edit_message_caption(
                chat_id=user_data["preview_chat_id"],
                message_id=user_data["preview_message_id"],
                caption="✅ **محتوا با موفقیت در کانال منتشر شد.**",
                reply_markup=None,
            )
        except:
            pass

    except Exception as e:
        logging.error(f"خطا در ارسال به کانال: {e}")
        await callback.message.answer("❌ خطا در انتشار. مطمئن شوید ربات در کانال ادمین است.")


async def cancel_post(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    try:
        await bot.delete_message(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"]
        )
        await callback.message.answer("❌ **انتشار لغو شد.**")
    except Exception as e:
        logging.error(f"خطا در لغو: {e}")
        await callback.message.answer("❌ خطا در لغو عملیات.")


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
