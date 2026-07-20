import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Union, List, Dict, Any

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
# توابع کمکی برای تشخیص نوع محتوا
# ========================

def get_media_type(message: types.Message) -> str:
    """تشخیص نوع رسانه‌ی ارسال شده"""
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
    """استخراج اطلاعات رسانه از پیام"""
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


def is_album(message: types.Message) -> bool:
    """تشخیص اینکه آیا پیام بخشی از یک البوم است"""
    return hasattr(message, 'media_group_id') and message.media_group_id is not None


async def get_album_messages(message: types.Message) -> List[types.Message]:
    """دریافت همه‌ی پیام‌های یک البوم (با استفاده از media_group_id)"""
    if not is_album(message):
        return [message]
    
    # متاسفانه aiogram به‌طور مستقیم البوم را پشتیبانی نمی‌کند
    # باید از روش جایگزین استفاده کنیم: ذخیره‌ی همه در یک گروه
    # در اینجا ما فقط یک پیام را ذخیره می‌کنیم و بعداً برای ارسال از InputMediaGroup استفاده می‌کنیم
    return [message]  # موقتاً فقط یک پیام


# ========================
# هندلرها
# ========================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_media)
    await message.answer(
        "سلام! 👋\n"
        "هر نوع محتوایی (عکس، ویدیو، موسیقی، متن، البوم) بفرستید.\n"
        "پس از تأیید و ویرایش (در صورت نیاز)، در کانال منتشر می‌شود.\n"
        "برای لغو، /cancel را بزنید."
    )


@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")


@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text)
async def handle_media(message: types.Message, state: FSMContext):
    """دریافت هر نوع محتوا و نمایش پیش‌نمایش"""
    media_type = get_media_type(message)
    media_data = extract_media_from_message(message)
    
    # ذخیره اطلاعات در state
    await state.update_data(
        media_type=media_type,
        media_data=media_data,
        is_album=is_album(message),
        caption=message.caption or "",
    )

    # ارسال پیش‌نمایش بر اساس نوع رسانه
    preview_message = await send_preview(message, media_type, media_data)
    
    await state.update_data(
        preview_chat_id=preview_message.chat.id,
        preview_message_id=preview_message.message_id,
    )
    await state.set_state(Form.showing_preview)


async def send_preview(message: types.Message, media_type: str, media_data: Dict[str, Any]) -> types.Message:
    """ارسال پیش‌نمایش بر اساس نوع رسانه"""
    caption = f"📸 **پیش‌نمایش پست**\n\n{media_data.get('caption', '') or '(بدون کپشن)'}"
    
    if media_type == "photo":
        return await message.answer_photo(
            photo=media_data["file_id"],
            caption=caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "video":
        return await message.answer_video(
            video=media_data["file_id"],
            caption=caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "audio":
        return await message.answer_audio(
            audio=media_data["file_id"],
            caption=caption,
            performer=media_data.get("performer"),
            title=media_data.get("title"),
            reply_markup=preview_keyboard()
        )
    elif media_type == "document":
        return await message.answer_document(
            document=media_data["file_id"],
            caption=caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "voice":
        return await message.answer_voice(
            voice=media_data["file_id"],
            caption=caption,
            reply_markup=preview_keyboard()
        )
    elif media_type == "video_note":
        return await message.answer_video_note(
            video_note=media_data["file_id"],
            reply_markup=preview_keyboard()
        )
    elif media_type == "text":
        # برای متن، یک پیام متنی با دکمه‌ها ارسال می‌کنیم
        text_preview = f"📝 **پیش‌نمایش پست**\n\n{media_data.get('text', '')}"
        return await message.answer(
            text_preview,
            reply_markup=preview_keyboard()
        )
    else:
        return await message.answer("❌ نوع فایل پشتیبانی نمی‌شود.")


@dp.callback_query(F.data.in_(["post", "cancel_post", "edit_caption"]), StateFilter(Form.showing_preview))
async def process_preview_actions(callback: types.CallbackQuery, state: FSMContext):
    """پردازش دکمه‌های پیش‌نمایش"""
    await callback.answer()

    user_data = await state.get_data()
    if not user_data:
        await callback.message.answer("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره محتوا را بفرستید.")
        await state.clear()
        return

    if callback.data == "post":
        # ===== ارسال به کانال =====
        await send_to_channel(callback, user_data)
        await state.clear()

    elif callback.data == "cancel_post":
        # ===== لغو =====
        await cancel_post(callback, user_data)
        await state.clear()

    elif callback.data == "edit_caption":
        # ===== ویرایش کپشن =====
        await callback.message.answer(
            f"✏️ کپشن جدید را به‌صورت متن ارسال کنید.\n"
            f"کپشن فعلی: {user_data.get('caption', '') or '(بدون کپشن)'}"
        )
        await state.set_state(Form.waiting_for_caption)


async def send_to_channel(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    """ارسال محتوا به کانال بر اساس نوع رسانه"""
    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    caption = user_data.get("caption", "")
    
    try:
        if media_type == "photo":
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=media_data["file_id"],
                caption=caption if caption else None,
            )
        elif media_type == "video":
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=media_data["file_id"],
                caption=caption if caption else None,
            )
        elif media_type == "audio":
            await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=media_data["file_id"],
                caption=caption if caption else None,
                performer=media_data.get("performer"),
                title=media_data.get("title"),
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=media_data["file_id"],
                caption=caption if caption else None,
            )
        elif media_type == "voice":
            await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=media_data["file_id"],
                caption=caption if caption else None,
            )
        elif media_type == "video_note":
            await bot.send_video_note(
                chat_id=CHANNEL_ID,
                video_note=media_data["file_id"],
            )
        elif media_type == "text":
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=media_data.get("text", ""),
            )
        
        # به‌روزرسانی پیام پیش‌نمایش
        await bot.edit_message_caption(
            chat_id=user_data["preview_chat_id"],
            message_id=user_data["preview_message_id"],
            caption="✅ **محتوا با موفقیت در کانال منتشر شد.**",
            reply_markup=None,
        )
    except Exception as e:
        logging.error(f"خطا در ارسال به کانال: {e}")
        await callback.message.answer(
            "❌ خطا در انتشار. مطمئن شوید ربات در کانال ادمین است."
        )


async def cancel_post(callback: types.CallbackQuery, user_data: Dict[str, Any]):
    """لغو انتشار و به‌روزرسانی پیش‌نمایش"""
    await bot.edit_message_caption(
        chat_id=user_data["preview_chat_id"],
        message_id=user_data["preview_message_id"],
        caption="❌ **انتشار لغو شد.**",
        reply_markup=None,
    )


@dp.message(StateFilter(Form.waiting_for_caption), F.text)
async def handle_new_caption(message: types.Message, state: FSMContext):
    """دریافت کپشن جدید و به‌روزرسانی پیش‌نمایش"""
    new_caption = message.text
    user_data = await state.get_data()

    if not user_data:
        await message.answer("متأسفم، داده‌ای پیدا نشد. لطفاً دوباره محتوا را بفرستید.")
        await state.clear()
        return

    # به‌روزرسانی کپشن در state
    await state.update_data(caption=new_caption)

    # به‌روزرسانی پیش‌نمایش
    try:
        media_type = user_data["media_type"]
        if media_type in ["photo", "video", "audio", "document", "voice"]:
            await bot.edit_message_caption(
                chat_id=user_data["preview_chat_id"],
                message_id=user_data["preview_message_id"],
                caption=f"📸 **پیش‌نمایش پست**\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=preview_keyboard(),
            )
        elif media_type == "text":
            await bot.edit_message_text(
                chat_id=user_data["preview_chat_id"],
                message_id=user_data["preview_message_id"],
                text=f"📝 **پیش‌نمایش پست**\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=preview_keyboard(),
            )
        else:
            # برای video_note که کپشن ندارد، پیام جدید ارسال می‌کنیم
            await message.answer(f"📸 **پیش‌نمایش پست**\n\n{new_caption if new_caption else '(بدون کپشن)'}")
        
        await message.answer("✅ کپشن به‌روزرسانی شد.")
    except Exception as e:
        logging.error(f"خطا در ادیت: {e}")
        await message.answer("❌ خطا در به‌روزرسانی پیش‌نمایش.")

    await state.set_state(Form.showing_preview)


@dp.message(StateFilter(Form.waiting_for_caption))
async def invalid_caption_input(message: types.Message):
    await message.answer("❌ لطفاً کپشن را به‌صورت متن ارسال کنید.")


@dp.message()
async def other_messages(message: types.Message):
    await message.answer(
        "❌ فقط محتوای معتبر بفرستید (عکس، ویدیو، موسیقی، فایل، متن).\n"
        "برای راهنمایی /start را بزنید."
    )


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
