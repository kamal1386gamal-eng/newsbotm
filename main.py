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
post_data: Dict[tuple, Dict[str, Any]] = {}
edit_state: Dict[int, tuple] = {}
album_buffer: Dict[str, Dict[str, Any]] = {}

# ---------- helpers ----------
def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def process_caption(caption: str) -> str:
    """Clean caption and add channel mention."""
    if not caption:
        caption = ""
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

# ---------- single media preview (excluding album) ----------
async def create_single_preview(message: types.Message):
    # 1. copy original user message to admin chat
    copied = await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    original_caption = message.caption or message.text or ""
    full_caption = f"📸 پیش‌نمایش پست\n\n{original_caption}"

    # determine media type for later handling
    if message.video_note:
        # video_note: can't edit caption, send separate text with buttons
        text_msg = await message.answer(
            full_caption if original_caption else "📸 پیش‌نمایش پست\n\n(بدون کپشن)",
            reply_markup=three_buttons()
        )
        store_key = (message.chat.id, text_msg.message_id)
        post_data[store_key] = {
            "type": "video_note",
            "vn_copied_id": copied.message_id,
            "text_msg_id": text_msg.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id
        }
    elif message.text and not (message.photo or message.video or message.audio or message.document or message.voice):
        # plain text: can't edit caption (it's a text message), so we edit text
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=copied.message_id,
                text=full_caption,
                reply_markup=three_buttons()
            )
        except:
            # fallback: delete and resend
            await delete_msg(message.chat.id, copied.message_id)
            new_msg = await message.answer(full_caption, reply_markup=three_buttons())
            copied.message_id = new_msg.message_id
        store_key = (message.chat.id, copied.message_id)
        post_data[store_key] = {
            "type": "text",
            "copied_msg_id": copied.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id
        }
    else:
        # media with caption: edit the copied message's caption
        try:
            await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=copied.message_id,
                caption=full_caption,
                reply_markup=three_buttons()
            )
            store_key = (message.chat.id, copied.message_id)
        except Exception as e:
            logging.warning(f"edit_message_caption failed: {e}")
            # fallback: delete copied, resend using file_id
            await delete_msg(message.chat.id, copied.message_id)
            # extract file_id from original
            if message.photo:
                m = await message.answer_photo(message.photo[-1].file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.video:
                m = await message.answer_video(message.video.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.audio:
                m = await message.answer_audio(message.audio.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.document:
                m = await message.answer_document(message.document.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.voice:
                m = await message.answer_voice(message.voice.file_id, caption=full_caption, reply_markup=three_buttons())
            else:
                return
            copied.message_id = m.message_id
            store_key = (message.chat.id, m.message_id)
        post_data[store_key] = {
            "type": "media",
            "copied_msg_id": copied.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id,
            "media_type": ("photo" if message.photo else
                           "video" if message.video else
                           "audio" if message.audio else
                           "document" if message.document else "voice")
        }

# ---------- album handling ----------
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

    # extract file_ids and meta
    items = []
    caption = ""
    copied_ids = []
    for m in msgs:
        if m.photo:
            items.append({"type": "photo", "file_id": m.photo[-1].file_id})
        elif m.video:
            items.append({
                "type": "video",
                "file_id": m.video.file_id,
                "duration": m.video.duration,
                "width": m.video.width,
                "height": m.video.height
            })
        else:
            continue  # skip non-photo/video in album (rare)
        if not caption and (m.caption or m.text):
            caption = m.caption or m.text or ""

        # copy each message to admin chat (for visual preview)
        try:
            c = await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=m.message_id)
            copied_ids.append(c.message_id)
        except:
            pass

    if not items:
        return

    full_caption = f"📸 آلبوم ({len(items)} آیتم)\n\n{caption if caption else '(بدون کپشن)'}"
    btn_msg = await bot.send_message(chat_id, full_caption, reply_markup=three_buttons())
    store_key = (chat_id, btn_msg.message_id)
    post_data[store_key] = {
        "type": "album",
        "items": items,
        "copied_msg_ids": copied_ids,
        "caption": caption,
        "chat_id": chat_id,
        "btn_msg_id": btn_msg.message_id,
        "original_message_ids": [m.message_id for m in msgs]
    }

# ---------- single media handler ----------
@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text, ~F.media_group_id)
async def handle_single(message: types.Message):
    if not is_allowed(message.from_user.id): return
    await create_single_preview(message)

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
    current = post_data[key].get("caption", "")
    await callback.message.answer(f"✏️ کپشن جدید را بفرستید.\nفعلی: {current or '(خالی)'}")

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
    full_preview = f"📸 پیش‌نمایش پست\n\n{new_caption if new_caption else '(بدون کپشن)'}"

    try:
        if data["type"] == "album":
            # update button message
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["btn_msg_id"],
                text=f"📸 آلبوم ({len(data['items'])} آیتم)\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=three_buttons()
            )
        elif data["type"] == "video_note":
            # update separate text message
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["text_msg_id"],
                text=full_preview,
                reply_markup=three_buttons()
            )
        elif data["type"] == "text":
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["copied_msg_id"],
                text=full_preview,
                reply_markup=three_buttons()
            )
        else:  # media with caption
            await bot.edit_message_caption(
                chat_id=data["chat_id"],
                message_id=data["copied_msg_id"],
                caption=full_preview,
                reply_markup=three_buttons()
            )
        await message.answer("✅ کپشن ویرایش شد.")
    except Exception as e:
        logging.error(f"Edit error: {e}")
        await message.answer("❌ ویرایش کپشن ممکن نیست. پست را لغو و دوباره ارسال کنید.")

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

    # cleanup all preview messages in admin chat
    if data["type"] == "video_note":
        await delete_msg(data["chat_id"], data["vn_copied_id"])
        await delete_msg(data["chat_id"], data["text_msg_id"])
    elif data["type"] == "album":
        for cid in data.get("copied_msg_ids", []):
            await delete_msg(data["chat_id"], cid)
        await delete_msg(data["chat_id"], data["btn_msg_id"])
    else:
        await delete_msg(data["chat_id"], data["copied_msg_id"])
    # also delete original user message(s)
    if data["type"] == "album":
        for oid in data.get("original_message_ids", []):
            await delete_msg(data["chat_id"], oid)
    else:
        await delete_msg(data["chat_id"], data.get("original_message_id"))

    if callback.data == "cancel_post":
        await callback.message.answer("❌ انتشار لغو شد.")
        return

    # publish to channel
    final_caption = process_caption(data.get("caption", ""))

    try:
        if data["type"] == "album":
            media_list = []
            for idx, item in enumerate(data["items"]):
                cap = final_caption if idx == 0 else ""
                if item["type"] == "photo":
                    media_list.append(types.InputMediaPhoto(media=item["file_id"], caption=cap))
                else:
                    media_list.append(types.InputMediaVideo(media=item["file_id"], caption=cap,
                                                            duration=item.get("duration"),
                                                            width=item.get("width"),
                                                            height=item.get("height")))
            await bot.send_media_group(CHANNEL_ID, media=media_list)
        elif data["type"] == "video_note":
            await bot.copy_message(CHANNEL_ID, from_chat_id=data["chat_id"], message_id=data["vn_copied_id"])
            if final_caption:
                await bot.send_message(CHANNEL_ID, final_caption)
        else:
            # copy the preview message to channel (it has media + full preview caption + buttons)
            sent = await bot.copy_message(
                CHANNEL_ID,
                from_chat_id=data["chat_id"],
                message_id=data["copied_msg_id"]
            )
            # edit the channel message to remove preview prefix and buttons
            if data["type"] == "text":
                await bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=sent.message_id,
                    text=final_caption,
                    reply_markup=None
                )
            else:
                await bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=sent.message_id,
                    caption=final_caption,
                    reply_markup=None
                )
        await callback.message.answer("✅ محتوا با موفقیت در کانال منتشر شد.")
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
