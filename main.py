import os
import re
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ متغیر محیطی BOT_TOKEN تنظیم نشده است.")

CHANNEL_ID = os.getenv("CHANNEL_ID", "@spark_news_tel")
ALLOWED_USER_ID = 8293164271

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------------------------------------------------------------------
# دیکشنری‌های اصلی
# -------------------------------------------------------------------
preview_data: Dict[tuple, Dict[str, Any]] = {}
editing_state: Dict[int, tuple] = {}
album_collector: Dict[str, Dict[str, Any]] = {}

# -------------------------------------------------------------------
# توابع کمکی
# -------------------------------------------------------------------
def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def get_media_type(message: types.Message) -> str:
    if message.photo: return "photo"
    if message.video: return "video"
    if message.audio: return "audio"
    if message.document: return "document"
    if message.voice: return "voice"
    if message.video_note: return "video_note"
    if message.text: return "text"
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

def process_caption_for_publishing(caption: str) -> str:
    if re.search(r"https?://\S+", caption):
        caption = re.sub(r"https?://\S+", "@spark_news_tel", caption, count=1)
    caption = re.sub(r"https?://\S+", "", caption)
    caption = re.sub(r"@(?!spark_news_tel\b)\w+", "", caption)
    caption = re.sub(r"#\w+", "", caption)
    if "@spark_news_tel" not in caption:
        if caption.strip():
            caption = caption.strip() + "\n"
        caption += "@spark_news_tel"
    else:
        caption = caption.strip()
    return caption

def preview_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ پست کردن", callback_data="post"),
        types.InlineKeyboardButton(text="✏️ ویرایش کپشن", callback_data="edit_caption"),
        types.InlineKeyboardButton(text="❌ لغو", callback_data="cancel_post"),
    )
    builder.adjust(2, 1)
    return builder.as_markup()

async def delete_preview_messages(chat_id: int, main_msg_id: Optional[int], extra_msg_id: Optional[int] = None):
    if main_msg_id:
        try: await bot.delete_message(chat_id, main_msg_id)
        except Exception as e: logging.warning(f"Could not delete main: {e}")
    if extra_msg_id:
        try: await bot.delete_message(chat_id, extra_msg_id)
        except Exception as e: logging.warning(f"Could not delete extra: {e}")

# -------------------------------------------------------------------
# تابع کمکی جدید: ارسال پیش‌نمایش با مدیا (برای استفاده هم در create_preview و هم ویرایش)
# -------------------------------------------------------------------
async def send_media_preview(reply_to: types.Message, media_type: str, media_data: dict, caption: str):
    full_caption = f"📸 پیش‌نمایش پست\n\n{caption if caption else '(بدون کپشن)'}"
    main_msg_id = extra_msg_id = None
    if media_type == "photo":
        msg = await reply_to.answer_photo(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    elif media_type == "video":
        msg = await reply_to.answer_video(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    elif media_type == "audio":
        msg = await reply_to.answer_audio(media_data["file_id"], caption=full_caption,
                                          performer=media_data.get("performer"), title=media_data.get("title"),
                                          reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    elif media_type == "document":
        msg = await reply_to.answer_document(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    elif media_type == "voice":
        msg = await reply_to.answer_voice(media_data["file_id"], caption=full_caption, reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    elif media_type == "video_note":
        vn_msg = await reply_to.answer_video_note(video_note=media_data["file_id"])
        txt_msg = await reply_to.answer(full_caption, reply_markup=preview_keyboard())
        main_msg_id = vn_msg.message_id
        extra_msg_id = txt_msg.message_id
    elif media_type == "text":
        msg = await reply_to.answer(full_caption, reply_markup=preview_keyboard())
        main_msg_id = msg.message_id
    else:
        msg = await reply_to.answer("❌ نوع فایل پشتیبانی نمی‌شود.")
        main_msg_id = msg.message_id
    return {"main": main_msg_id, "extra": extra_msg_id}

# -------------------------------------------------------------------
# ارسال پیش‌نمایش و ذخیره‌سازی (با استفاده از تابع send_media_preview)
# -------------------------------------------------------------------
async def create_preview(
    original_message: types.Message,
    media_type: str,
    media_data: Dict[str, Any],
    caption: str,
    album: bool = False
):
    caption_text = caption if caption else '(بدون کپشن)'
    if album:
        text = f"📸 آلبوم ({len(media_data['items'])} آیتم)\n\n{caption_text}"
        msg = await original_message.answer(text, reply_markup=preview_keyboard())
        store_key = (msg.chat.id, msg.message_id)
        preview_data[store_key] = {
            "media_type": "album",
            "media_data": media_data,
            "caption": caption,
            "main_chat_id": msg.chat.id,
            "main_message_id": msg.message_id,
            "extra_message_id": None,
            "original_chat_id": original_message.chat.id,
            "original_message_id": original_message.message_id,
        }
        return

    ids = await send_media_preview(original_message, media_type, media_data, caption)
    main_id = ids["main"]
    extra_id = ids.get("extra")
    store_key = (original_message.chat.id, extra_id) if extra_id else (original_message.chat.id, main_id)
    preview_data[store_key] = {
        "media_type": media_type,
        "media_data": media_data,
        "caption": caption,
        "main_chat_id": original_message.chat.id,
        "main_message_id": main_id,
        "extra_message_id": extra_id,
        "original_chat_id": original_message.chat.id,
        "original_message_id": original_message.message_id,
    }

# -------------------------------------------------------------------
# هندلرها
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await message.answer("سلام! هر محتوایی بفرستید. چند پست همزمان می‌توانند پیش‌نمایش داشته باشند. /cancel برای لغو.")

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await message.answer("اگر پیش‌نمایشی باز است، از دکمه «لغو» زیر آن استفاده کنید.")

@dp.message(F.media_group_id)
async def handle_album_item(message: types.Message):
    if not is_allowed(message.from_user.id): return
    media_group_id = message.media_group_id
    if media_group_id not in album_collector:
        album_collector[media_group_id] = {"messages": [], "timer": None}
    album_collector[media_group_id]["messages"].append(message)
    if not album_collector[media_group_id]["timer"]:
        task = asyncio.create_task(process_album(media_group_id, message.chat.id, message))
        album_collector[media_group_id]["timer"] = task

async def process_album(media_group_id: str, chat_id: int, trigger_message: types.Message):
    await asyncio.sleep(1)
    group_data = album_collector.pop(media_group_id, None)
    if not group_data: return
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
    if not items: return

    album_data = {"type": "album", "items": items, "caption": caption}
    await create_preview(trigger_message, "album", album_data, caption, album=True)

@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text, ~F.media_group_id)
async def handle_single_media(message: types.Message):
    if not is_allowed(message.from_user.id): return
    media_type = get_media_type(message)
    media_data = extract_media_from_message(message)
    caption = message.caption or ""
    if media_type == "text":
        caption = media_data.get("text", "")
    await create_preview(message, media_type, media_data, caption)

# -------------------------------------------------------------------
# ویرایش کپشن (بازنویسی شده)
# -------------------------------------------------------------------
@dp.callback_query(F.data == "edit_caption")
async def edit_caption_start(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    store_key = (callback.message.chat.id, callback.message.message_id)
    data = preview_data.get(store_key)
    if not data:
        await callback.message.answer("⚠️ داده‌های این پست یافت نشد.")
        return
    editing_state[callback.from_user.id] = store_key
    current_caption = data.get("caption", "")
    await callback.message.answer(f"✏️ کپشن جدید را بفرستید.\nفعلی: {current_caption or '(خالی)'}")

@dp.message(F.text)
async def handle_text_for_edit(message: types.Message):
    if not is_allowed(message.from_user.id): return
    user_id = message.from_user.id
    if user_id in editing_state:
        store_key = editing_state.pop(user_id)
        data = preview_data.get(store_key)
        if not data:
            await message.answer("داده‌های پست یافت نشد.")
            return

        new_caption = message.text
        data["caption"] = new_caption

        # حذف پیش‌نمایش قبلی
        await delete_preview_messages(data["main_chat_id"], data["main_message_id"], data.get("extra_message_id"))

        if data["media_type"] == "album":
            caption_text = new_caption if new_caption else '(بدون کپشن)'
            text = f"📸 آلبوم ({len(data['media_data']['items'])} آیتم)\n\n{caption_text}"
            msg = await message.answer(text, reply_markup=preview_keyboard())
            new_store_key = (msg.chat.id, msg.message_id)
            preview_data[new_store_key] = {
                **data,
                "main_chat_id": msg.chat.id,
                "main_message_id": msg.message_id,
                "extra_message_id": None,
            }
        else:
            ids = await send_media_preview(message, data["media_type"], data["media_data"], new_caption)
            main_id = ids["main"]
            extra_id = ids.get("extra")
            new_store_key = (message.chat.id, extra_id) if extra_id else (message.chat.id, main_id)
            preview_data[new_store_key] = {
                **data,
                "main_chat_id": message.chat.id,
                "main_message_id": main_id,
                "extra_message_id": extra_id,
            }
        await message.answer("✅ کپشن ویرایش شد. پیش‌نمایش جدید را ببینید.")
    else:
        await message.answer("❌ لطفاً محتوای معتبر ارسال کنید یا از دکمه‌ها استفاده کنید.")

# -------------------------------------------------------------------
# دکمه‌های پست و لغو
# -------------------------------------------------------------------
@dp.callback_query(F.data.in_(["post", "cancel_post"]))
async def process_post_actions(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    store_key = (callback.message.chat.id, callback.message.message_id)
    data = preview_data.pop(store_key, None)
    if not data:
        await callback.message.answer("⚠️ داده‌های این پست یافت نشد.")
        return

    # حذف پیش‌نمایش
    await delete_preview_messages(data["main_chat_id"], data["main_message_id"], data.get("extra_message_id"))

    # حذف پیام اصلی فروارد شده
    orig_chat = data.get("original_chat_id")
    orig_msg = data.get("original_message_id")
    if orig_chat and orig_msg:
        try: await bot.delete_message(orig_chat, orig_msg)
        except Exception: pass

    if callback.data == "cancel_post":
        await callback.message.answer("❌ انتشار لغو شد.")
        return

    # post
    media_type = data["media_type"]
    media_data = data["media_data"]
    caption = data.get("caption", "")
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

        await callback.message.answer("✅ محتوا با موفقیت در کانال منتشر شد.")
    except Exception as e:
        logging.error(f"خطا در انتشار: {e}")
        await callback.message.answer("❌ خطا در انتشار. ربات ادمین است؟")

@dp.message()
async def other_messages(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await message.answer("❌ لطفاً محتوای معتبر ارسال کنید.")

# -------------------------------------------------------------------
# اجرا
# -------------------------------------------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
