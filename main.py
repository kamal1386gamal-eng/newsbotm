import os
import re
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any, List, Optional

# -------------------------------------------------------------------
# تنظیمات
# -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ متغیر محیطی BOT_TOKEN تنظیم نشده است.")

CHANNEL_ID = os.getenv("CHANNEL_ID", "@spark_news_tel")
ALLOWED_USER_ID = 8293164271        # فقط این کاربر مجاز است

# -------------------------------------------------------------------
# FSM
# -------------------------------------------------------------------
class Form(StatesGroup):
    showing_preview = State()
    waiting_for_caption = State()

storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# -------------------------------------------------------------------
# Middleware برای محدود کردن کاربران
# -------------------------------------------------------------------
class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.TelegramObject, data: dict):
        user_id = None
        if hasattr(event, 'from_user') and event.from_user:
            user_id = event.from_user.id
        if user_id != ALLOWED_USER_ID:
            return  # بی‌صدا ignore می‌شود
        return await handler(event, data)

dp.update.outer_middleware(AccessMiddleware())

# -------------------------------------------------------------------
# جمع‌آوری آلبوم‌ها
# -------------------------------------------------------------------
album_collector: Dict[str, Dict[str, Any]] = {}

# -------------------------------------------------------------------
# توابع کمکی
# -------------------------------------------------------------------
def get_media_type(message: types.Message) -> str:
    if message.photo:        return "photo"
    if message.video:        return "video"
    if message.audio:        return "audio"
    if message.document:     return "document"
    if message.voice:        return "voice"
    if message.video_note:   return "video_note"
    if message.text:         return "text"
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
    album: bool = False
) -> Dict[str, Any]:
    caption_text = caption if caption else '(بدون کپشن)'
    result = {"main_chat_id": target_message.chat.id, "main_message_id": None, "extra_message_id": None}

    if album:
        text = f"📸 آلبوم ({len(media_data['items'])} آیتم)\n\n{caption_text}"
        msg = await target_message.answer(text, reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
        return result

    full_caption = f"📸 پیش‌نمایش پست\n\n{caption_text}"

    if media_type == "photo":
        msg = await target_message.answer_photo(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    elif media_type == "video":
        msg = await target_message.answer_video(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    elif media_type == "audio":
        msg = await target_message.answer_audio(media_data["file_id"], caption=full_caption,
                                                performer=media_data.get("performer"), title=media_data.get("title"),
                                                reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    elif media_type == "document":
        msg = await target_message.answer_document(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    elif media_type == "voice":
        msg = await target_message.answer_voice(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    elif media_type == "video_note":
        vn_msg = await target_message.answer_video_note(video_note=media_data["file_id"])
        txt_msg = await target_message.answer(full_caption, reply_markup=preview_keyboard())
        result["main_message_id"] = vn_msg.message_id
        result["extra_message_id"] = txt_msg.message_id
    elif media_type == "text":
        msg = await target_message.answer(f"📝 پیش‌نمایش پست\n\n{caption_text}", reply_markup=preview_keyboard())
        result["main_message_id"] = msg.message_id
    else:
        msg = await target_message.answer("❌ نوع فایل پشتیبانی نمی‌شود.")
        result["main_message_id"] = msg.message_id
    return result

async def delete_preview_messages(chat_id: int, main_msg_id: Optional[int], extra_msg_id: Optional[int] = None):
    if main_msg_id:
        try: await bot.delete_message(chat_id, main_msg_id)
        except Exception as e: logging.warning(f"Could not delete main: {e}")
    if extra_msg_id:
        try: await bot.delete_message(chat_id, extra_msg_id)
        except Exception as e: logging.warning(f"Could not delete extra: {e}")

def process_caption_for_publishing(caption: str) -> str:
    # حذف همه لینک‌ها، منشن‌ها و هشتگ‌ها
    cleaned = re.sub(r"https?://\S+", "", caption)
    cleaned = re.sub(r"@\w+", "", cleaned)
    cleaned = re.sub(r"#\w+", "", cleaned)
    cleaned = cleaned.strip()
    if cleaned:
        cleaned += "\n"
    cleaned += "@spark_news_tel"
    return cleaned

def preview_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ پست کردن", callback_data="post"),
        types.InlineKeyboardButton(text="✏️ ویرایش کپشن", callback_data="edit_caption"),
        types.InlineKeyboardButton(text="❌ لغو", callback_data="cancel_post"),
    )
    builder.adjust(2, 1)
    return builder.as_markup()

# -------------------------------------------------------------------
# پردازش آلبوم
# -------------------------------------------------------------------
async def process_album(media_group_id: str, chat_id: int, bot_instance: Bot, state: FSMContext, message: types.Message):
    await asyncio.sleep(1)
    group_data = album_collector.pop(media_group_id, None)
    if not group_data:
        return
    messages: List[types.Message] = group_data["messages"]
    messages.sort(key=lambda m: m.message_id)

    items = []
    caption = ""
    for msg in messages:
        t = get_media_type(msg)
        if t in ("photo", "video"):
            item = {"type": t, "file_id": msg.photo[-1].file_id if t == "photo" else msg.video.file_id}
            if t == "video":
                item["duration"] = msg.video.duration
                item["width"] = msg.video.width
                item["height"] = msg.video.height
            items.append(item)
            if not caption and msg.caption:
                caption = msg.caption
    if not items:
        return

    album_data = {"type": "album", "items": items, "caption": caption}
    await state.update_data(media_type="album", media_data=album_data, caption=caption)

    preview_info = await send_preview(message, "album", album_data, caption, album=True)
    await state.update_data(
        preview_chat_id=preview_info["main_chat_id"],
        preview_main_message_id=preview_info["main_message_id"],
        preview_extra_message_id=None,
    )
    await state.set_state(Form.showing_preview)

# -------------------------------------------------------------------
# هندلرها
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("سلام! فقط شما مجاز به استفاده هستید. هر محتوایی بفرستید (آلبوم هم پشتیبانی می‌شود). /cancel برای لغو.")

@dp.message(Command("cancel"))
@dp.message(F.text.casefold() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await delete_preview_messages(data.get("preview_chat_id"), data.get("preview_main_message_id"), data.get("preview_extra_message_id"))
    await state.clear()
    await message.answer("❌ عملیات لغو شد.")

@dp.message(F.media_group_id)
async def handle_album_item(message: types.Message, state: FSMContext):
    media_group_id = message.media_group_id
    if media_group_id not in album_collector:
        album_collector[media_group_id] = {"messages": [], "timer": None}
    album_collector[media_group_id]["messages"].append(message)
    if not album_collector[media_group_id]["timer"]:
        task = asyncio.create_task(process_album(media_group_id, message.chat.id, bot, state, message))
        album_collector[media_group_id]["timer"] = task

@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text, ~F.media_group_id)
async def handle_single_media(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        data = await state.get_data()
        await delete_preview_messages(data.get("preview_chat_id"), data.get("preview_main_message_id"), data.get("preview_extra_message_id"))
        await state.clear()

    media_type = get_media_type(message)
    media_data = extract_media_from_message(message)
    caption = message.caption or ""
    if media_type == "text":
        caption = media_data.get("text", "")

    await state.update_data(media_type=media_type, media_data=media_data, caption=caption)
    preview_info = await send_preview(message, media_type, media_data, caption)
    await state.update_data(
        preview_chat_id=preview_info["main_chat_id"],
        preview_main_message_id=preview_info["main_message_id"],
        preview_extra_message_id=preview_info.get("extra_message_id"),
    )
    await state.set_state(Form.showing_preview)

@dp.message(StateFilter(Form.waiting_for_caption), F.text)
async def handle_new_caption(message: types.Message, state: FSMContext):
    new_caption = message.text
    user_data = await state.get_data()
    if not user_data:
        await message.answer("داده‌ای یافت نشد."); await state.clear(); return

    media_type = user_data["media_type"]
    media_data = user_data["media_data"]
    chat_id = user_data["preview_chat_id"]
    main_msg_id = user_data.get("preview_main_message_id")
    extra_msg_id = user_data.get("preview_extra_message_id")

    if media_type == "album":
        caption_text = new_caption if new_caption else '(بدون کپشن)'
        new_text = f"📸 آلبوم ({len(media_data['items'])} آیتم)\n\n{caption_text}"
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=main_msg_id, text=new_text, reply_markup=preview_keyboard())
            await state.update_data(caption=new_caption)
            await message.answer("✅ کپشن با موفقیت ویرایش شد.")
            await state.set_state(Form.showing_preview)
            return
        except Exception as e:
            logging.warning(f"edit album preview failed: {e}")

    caption_text = new_caption if new_caption else '(بدون کپشن)'
    full_caption = f"📸 پیش‌نمایش پست\n\n{caption_text}"

    if media_type in ("photo", "video", "audio", "document", "voice"):
        try:
            await bot.edit_message_caption(chat_id=chat_id, message_id=main_msg_id, caption=full_caption, reply_markup=preview_keyboard())
            await state.update_data(caption=new_caption)
            await message.answer("✅ کپشن با موفقیت ویرایش شد.")
            await state.set_state(Form.showing_preview)
            return
        except Exception as e:
            logging.warning(f"edit_message_caption failed: {e}")

    await delete_preview_messages(chat_id, main_msg_id, extra_msg_id)
    if media_type == "text":
        media_data["text"] = new_caption

    new_info = await send_preview(message, media_type, media_data, new_caption)
    await state.update_data(caption=new_caption, preview_chat_id=new_info["main_chat_id"],
                           preview_main_message_id=new_info["main_message_id"], preview_extra_message_id=new_info.get("extra_message_id"), media_data=media_data)
    await message.answer("✅ کپشن ویرایش شد. پیش‌نمایش جدید را ببینید.")
    await state.set_state(Form.showing_preview)

@dp.message(StateFilter(Form.waiting_for_caption))
async def abort_caption_and_new_media(message: types.Message, state: FSMContext):
    await message.answer("⚠️ ویرایش کپشن لغو شد. محتوای جدید دریافت شد.")
    data = await state.get_data()
    await delete_preview_messages(data.get("preview_chat_id"), data.get("preview_main_message_id"), data.get("preview_extra_message_id"))
    await state.clear()
    if message.media_group_id:
        await handle_album_item(message, state)
    else:
        await handle_single_media(message, state)

@dp.callback_query(F.data.in_(["post", "cancel_post", "edit_caption"]), StateFilter(Form.showing_preview))
async def process_preview_actions(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_data = await state.get_data()
    if not user_data:
        await callback.message.answer("داده‌ای یافت نشد."); await state.clear(); return

    if callback.data == "post":
        media_type = user_data["media_type"]
        media_data = user_data["media_data"]
        caption = user_data.get("caption", "")
        final_caption = process_caption_for_publishing(caption)

        try:
            if media_type == "album":
                media_list = []
                for idx, item in enumerate(media_data["items"]):
                    cap = final_caption if idx == 0 else ""
                    if item["type"] == "photo":
                        media_list.append(types.InputMediaPhoto(media=item["file_id"], caption=cap))
                    else:
                        media_list.append(types.InputMediaVideo(media=item["file_id"], caption=cap,
                                                                duration=item.get("duration"), width=item.get("width"), height=item.get("height")))
                await bot.send_media_group(CHANNEL_ID, media=media_list)
            else:
                if media_type == "photo":
                    await bot.send_photo(CHANNEL_ID, media_data["file_id"], caption=final_caption)
                elif media_type == "video":
                    await bot.send_video(CHANNEL_ID, media_data["file_id"], caption=final_caption)
                elif media_type == "audio":
                    await bot.send_audio(CHANNEL_ID, media_data["file_id"], caption=final_caption,
                                         performer=media_data.get("performer"), title=media_data.get("title"))
                elif media_type == "document":
                    await bot.send_document(CHANNEL_ID, media_data["file_id"], caption=final_caption)
                elif media_type == "voice":
                    await bot.send_voice(CHANNEL_ID, media_data["file_id"], caption=final_caption)
                elif media_type == "video_note":
                    await bot.send_video_note(CHANNEL_ID, media_data["file_id"])
                    if final_caption:
                        await bot.send_message(CHANNEL_ID, final_caption)
                elif media_type == "text":
                    await bot.send_message(CHANNEL_ID, final_caption)

            await delete_preview_messages(user_data["preview_chat_id"], user_data.get("preview_main_message_id"), user_data.get("preview_extra_message_id"))
            await callback.message.answer("✅ محتوا با موفقیت در کانال منتشر شد.")
        except Exception as e:
            logging.error(f"خطا در انتشار: {e}")
            await callback.message.answer("❌ خطا در انتشار. ربات ادمین است؟")
        await state.clear()

    elif callback.data == "cancel_post":
        await delete_preview_messages(user_data["preview_chat_id"], user_data.get("preview_main_message_id"), user_data.get("preview_extra_message_id"))
        await callback.message.answer("❌ انتشار لغو شد.")
        await state.clear()

    elif callback.data == "edit_caption":
        current_caption = user_data.get("caption", "")
        await callback.message.answer(f"✏️ کپشن جدید را بفرستید.\nفعلی: {current_caption or '(خالی)'}")
        await state.set_state(Form.waiting_for_caption)

@dp.message()
async def other_messages(message: types.Message):
    # این بخش فقط برای کاربران مجاز اجرا می‌شود، در غیر این صورت میدلور متوقف کرده است
    await message.answer("❌ لطفاً محتوای معتبر ارسال کنید.")

# -------------------------------------------------------------------
# اجرا
# -------------------------------------------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
