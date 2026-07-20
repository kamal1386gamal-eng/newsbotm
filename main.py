import os
import re
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")

CHANNEL_ID = os.getenv("CHANNEL_ID", "@spark_news_tel")
ALLOWED_USER_ID = 8293164271

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------- data ----------
# key = (chat_id, message_id_of_button_message)
post_data: Dict[tuple, Dict[str, Any]] = {}
edit_state: Dict[int, tuple] = {}
album_buffer: Dict[str, Dict[str, Any]] = {}

# ---------- helpers ----------
def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def get_media_type(msg: types.Message) -> str:
    if msg.photo: return "photo"
    if msg.video: return "video"
    if msg.audio: return "audio"
    if msg.document: return "document"
    if msg.voice: return "voice"
    if msg.video_note: return "video_note"
    if msg.text: return "text"
    return "unknown"

def extract_single_media(msg: types.Message) -> dict:
    """Extract file_id and meta for a single message (not album)."""
    t = get_media_type(msg)
    data = {"type": t, "caption": msg.caption or ""}
    if t == "photo":
        data["file_id"] = msg.photo[-1].file_id
    elif t == "video":
        data["file_id"] = msg.video.file_id
        data["duration"] = msg.video.duration
        data["width"] = msg.video.width
        data["height"] = msg.video.height
    elif t == "audio":
        data["file_id"] = msg.audio.file_id
        data["duration"] = msg.audio.duration
        data["performer"] = msg.audio.performer
        data["title"] = msg.audio.title
    elif t == "document":
        data["file_id"] = msg.document.file_id
        data["file_name"] = msg.document.file_name
    elif t == "voice":
        data["file_id"] = msg.voice.file_id
        data["duration"] = msg.voice.duration
    elif t == "video_note":
        data["file_id"] = msg.video_note.file_id
        data["duration"] = msg.video_note.duration
        data["length"] = msg.video_note.length
    elif t == "text":
        data["text"] = msg.text
    return data

def process_caption(caption: str) -> str:
    if not caption:
        caption = ""
    # جایگزینی لینک‌ها و اضافه کردن ایدی کانال (طبق قبلی)
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

def three_buttons():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ پست کردن", callback_data="post"),
        types.InlineKeyboardButton(text="✏️ ویرایش کپشن", callback_data="edit_caption"),
        types.InlineKeyboardButton(text="❌ لغو", callback_data="cancel_post"),
    )
    builder.adjust(2, 1)
    return builder.as_markup()

async def delete_msg(chat_id: int, msg_id: Optional[int]):
    if msg_id:
        try: await bot.delete_message(chat_id, msg_id)
        except Exception: pass

async def cleanup_preview(data: dict):
    """Delete all preview messages."""
    # main button message
    if data.get("main_chat_id") and data.get("main_message_id"):
        await delete_msg(data["main_chat_id"], data["main_message_id"])
    # extra (video_note text)
    if data.get("extra_chat_id") and data.get("extra_message_id"):
        await delete_msg(data["extra_chat_id"], data["extra_message_id"])
    # forwarded album media
    for fid in data.get("forwarded_ids", []):
        await delete_msg(data["main_chat_id"], fid)  # all in same admin chat
    # original user message
    if data.get("original_chat_id") and data.get("original_message_id"):
        await delete_msg(data["original_chat_id"], data["original_message_id"])

# ---------- create preview ----------
async def create_preview(message: types.Message, media_type: str, media_data: dict, caption: str, album: bool = False):
    full_caption = f"📸 پیش‌نمایش پست\n\n{caption if caption else '(بدون کپشن)'}"

    if album:
        # آلبوم: فوروارد همه مدیاها، سپس یک پیام متنی با دکمه
        items = media_data["items"]
        forwarded = []
        for idx, item in enumerate(items):
            # send album items from original message? We don't have the original messages anymore;
            # we only have their file_ids. Better to use send_media_group? Can't. 
            # We stored the original messages in the buffer, so we have them.
            # But we are inside create_preview for album, we have trigger_message 
            # and the original messages are in album_collector. 
            # We'll handle album creation separately outside this function.
            pass

    else:
        # تکی
        markup = three_buttons()
        main_id = extra_id = None
        if media_type == "photo":
            msg = await message.answer_photo(media_data["file_id"], caption=full_caption, reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        elif media_type == "video":
            msg = await message.answer_video(media_data["file_id"], caption=full_caption, reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        elif media_type == "audio":
            msg = await message.answer_audio(media_data["file_id"], caption=full_caption,
                                             performer=media_data.get("performer"), title=media_data.get("title"),
                                             reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        elif media_type == "document":
            msg = await message.answer_document(media_data["file_id"], caption=full_caption, reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        elif media_type == "voice":
            msg = await message.answer_voice(media_data["file_id"], caption=full_caption, reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        elif media_type == "video_note":
            vn_msg = await message.answer_video_note(media_data["file_id"])
            txt_msg = await message.answer(full_caption, reply_markup=markup)
            main_id = vn_msg.message_id
            extra_id = txt_msg.message_id
            key = (message.chat.id, extra_id)  # دکمه روی این پیامه
        elif media_type == "text":
            msg = await message.answer(full_caption, reply_markup=markup)
            main_id = msg.message_id
            key = (message.chat.id, main_id)
        else:
            await message.answer("نوع فایل پشتیبانی نمی‌شود.")
            return

        post_data[key] = {
            "type": "single",
            "media_type": media_type,
            "media_data": media_data,
            "caption": caption,
            "main_chat_id": message.chat.id,
            "main_message_id": main_id,
            "extra_chat_id": message.chat.id if extra_id else None,
            "extra_message_id": extra_id,
            "original_chat_id": message.chat.id,
            "original_message_id": message.message_id,
            "forwarded_ids": [],
        }

# ---------- handler for album (custom) ----------
@dp.message(F.media_group_id)
async def on_album_part(message: types.Message):
    if not is_allowed(message.from_user.id): return
    gid = message.media_group_id
    if gid not in album_buffer:
        album_buffer[gid] = {"messages": [], "timer": None}
    album_buffer[gid]["messages"].append(message)
    if not album_buffer[gid]["timer"]:
        album_buffer[gid]["timer"] = asyncio.create_task(process_album(gid, message.chat.id))

async def process_album(gid: str, chat_id: int):
    await asyncio.sleep(1)
    buf = album_buffer.pop(gid, None)
    if not buf: return
    msgs: List[types.Message] = buf["messages"]
    msgs.sort(key=lambda m: m.message_id)

    items = []
    caption = ""
    for m in msgs:
        t = get_media_type(m)
        if t in ("photo", "video"):
            item = {"type": t}
            if t == "photo":
                item["file_id"] = m.photo[-1].file_id
            else:
                item["file_id"] = m.video.file_id
                item["duration"] = m.video.duration
                item["width"] = m.video.width
                item["height"] = m.video.height
            items.append(item)
            if not caption and m.caption:
                caption = m.caption
    if not items:
        return

    # 1. فوروارد تمام پیام‌ها به ادمین (بدون دکمه)
    forwarded_ids = []
    for m in msgs:
        try:
            sent = await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=m.message_id)
            forwarded_ids.append(sent.message_id)
        except Exception:
            pass

    # 2. پیام اعلان با دکمه
    full_caption = f"📸 آلبوم ({len(items)} آیتم)\n\n{caption if caption else '(بدون کپشن)'}"
    notif = await bot.send_message(chat_id, full_caption, reply_markup=three_buttons())
    key = (chat_id, notif.message_id)
    post_data[key] = {
        "type": "album",
        "media_type": "album",
        "media_data": {"items": items},
        "caption": caption,
        "main_chat_id": chat_id,
        "main_message_id": notif.message_id,   # پیام دکمه
        "extra_chat_id": None,
        "extra_message_id": None,
        "forwarded_ids": forwarded_ids,
        "original_chat_id": chat_id,
        "original_message_id": msgs[0].message_id,  # برای حذف اولین پیام (اختیاری)
        "all_original_ids": [m.message_id for m in msgs],
    }

# ---------- single media ----------
@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text, ~F.media_group_id)
async def handle_single(message: types.Message):
    if not is_allowed(message.from_user.id): return
    media_type = get_media_type(message)
    media_data = extract_single_media(message)
    caption = message.caption or ""
    if media_type == "text":
        caption = media_data.get("text", "")
    await create_preview(message, media_type, media_data, caption)

# ---------- edit caption ----------
@dp.callback_query(F.data == "edit_caption")
async def edit_caption_start(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    key = (callback.message.chat.id, callback.message.message_id)
    if key not in post_data:
        await callback.message.answer("⚠️ این پست دیگر معتبر نیست.")
        return
    edit_state[callback.from_user.id] = key
    await callback.message.answer("✏️ کپشن جدید را ارسال کنید:")

@dp.message(F.text)
async def handle_new_caption(message: types.Message):
    if not is_allowed(message.from_user.id): return
    uid = message.from_user.id
    if uid not in edit_state:
        await message.answer("لطفاً یک فایل بفرستید یا از دکمه‌ها استفاده کنید.")
        return

    key = edit_state.pop(uid)
    data = post_data.get(key)
    if not data:
        await message.answer("پست منقضی شده است.")
        return

    new_caption = message.text
    data["caption"] = new_caption
    full_caption = f"📸 پیش‌نمایش پست\n\n{new_caption if new_caption else '(بدون کپشن)'}"

    try:
        if data["type"] == "single":
            mt = data["media_type"]
            if mt in ("photo", "video", "audio", "document", "voice"):
                # ویرایش مستقیم کپشن روی پیام مدیا
                await bot.edit_message_caption(
                    chat_id=data["main_chat_id"],
                    message_id=data["main_message_id"],
                    caption=full_caption,
                    reply_markup=three_buttons()
                )
            elif mt == "video_note":
                # ویرایش پیام متنی که دکمه‌ها را دارد
                await bot.edit_message_text(
                    chat_id=data["extra_chat_id"],
                    message_id=data["extra_message_id"],
                    text=full_caption,
                    reply_markup=three_buttons()
                )
            elif mt == "text":
                await bot.edit_message_text(
                    chat_id=data["main_chat_id"],
                    message_id=data["main_message_id"],
                    text=full_caption,
                    reply_markup=three_buttons()
                )
            else:
                raise ValueError("unknown")
        else:  # album
            # ویرایش پیام اعلان
            await bot.edit_message_text(
                chat_id=data["main_chat_id"],
                message_id=data["main_message_id"],
                text=f"📸 آلبوم ({len(data['media_data']['items'])} آیتم)\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=three_buttons()
            )

        await message.answer("✅ کپشن ویرایش شد. می‌توانید دوباره پیش‌نمایش را بررسی کنید.")
    except Exception as e:
        logging.error(f"Edit failed: {e}")
        await message.answer("❌ متأسفانه نتوانستم کپشن را ویرایش کنم. لطفاً دوباره تلاش کنید یا پست را لغو کنید.")

# ---------- post & cancel ----------
@dp.callback_query(F.data.in_(["post", "cancel_post"]))
async def handle_post_or_cancel(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    key = (callback.message.chat.id, callback.message.message_id)
    data = post_data.pop(key, None)
    if not data:
        await callback.message.answer("⚠️ پست یافت نشد.")
        return

    if callback.data == "cancel_post":
        await cleanup_preview(data)
        # حذف همه پیام‌های اصلی آلبوم هم اختیاری (done in cleanup)
        await callback.message.answer("❌ انتشار لغو شد.")
        return

    # post
    await cleanup_preview(data)

    media_type = data["media_type"]
    media_data = data["media_data"]
    final_caption = process_caption(data.get("caption", ""))

    try:
        if data["type"] == "album":
            items = media_data["items"]
            media_list = []
            for i, item in enumerate(items):
                cap = final_caption if i == 0 else ""
                if item["type"] == "photo":
                    media_list.append(types.InputMediaPhoto(media=item["file_id"], caption=cap))
                else:
                    media_list.append(types.InputMediaVideo(media=item["file_id"], caption=cap,
                                                            duration=item.get("duration"), width=item.get("width"), height=item.get("height")))
            await bot.send_media_group(CHANNEL_ID, media=media_list)
        else:
            mt = data["media_type"]
            if mt == "photo":
                await bot.send_photo(CHANNEL_ID, media_data["file_id"], caption=final_caption)
            elif mt == "video":
                await bot.send_video(CHANNEL_ID, media_data["file_id"], caption=final_caption)
            elif mt == "audio":
                await bot.send_audio(CHANNEL_ID, media_data["file_id"], caption=final_caption,
                                     performer=media_data.get("performer"), title=media_data.get("title"))
            elif mt == "document":
                await bot.send_document(CHANNEL_ID, media_data["file_id"], caption=final_caption)
            elif mt == "voice":
                await bot.send_voice(CHANNEL_ID, media_data["file_id"], caption=final_caption)
            elif mt == "video_note":
                await bot.send_video_note(CHANNEL_ID, media_data["file_id"])
                if final_caption:
                    await bot.send_message(CHANNEL_ID, final_caption)
            elif mt == "text":
                await bot.send_message(CHANNEL_ID, final_caption)

        await callback.message.answer("✅ با موفقیت در کانال منتشر شد.")
    except Exception as e:
        logging.error(f"Publish error: {e}")
        await callback.message.answer(f"❌ خطا در انتشار: {e}")

# ---------- fallback ----------
@dp.message()
async def fallback(message: types.Message):
    if is_allowed(message.from_user.id):
        await message.answer("لطفاً یک عکس، فیلم، فایل، آلبوم یا متن ارسال کنید.")

# ---------- run ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
