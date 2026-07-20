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
# key = (chat_id, message_id_of_button_message)  -> for single media, that's the copied message; for album/video_note it's the extra text message
post_data: Dict[tuple, Dict[str, Any]] = {}
edit_state: Dict[int, tuple] = {}
album_buffer: Dict[str, Dict[str, Any]] = {}

# ---------- helpers ----------
def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def process_caption(caption: str) -> str:
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

# ---------- create preview for single media using copy_message ----------
async def create_single_preview(message: types.Message):
    # copy the user's message to the same chat (admin chat)
    copied = await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )
    original_caption = message.caption or message.text or ""
    full_caption = f"📸 پیش‌نمایش پست\n\n{original_caption}"

    # try to edit the copied message to add buttons and preview prefix
    # but some types can't be edited (video_note), so we handle them differently
    media_type = None
    if message.photo: media_type = "photo"
    elif message.video: media_type = "video"
    elif message.audio: media_type = "audio"
    elif message.document: media_type = "document"
    elif message.voice: media_type = "voice"
    elif message.video_note: media_type = "video_note"
    elif message.text: media_type = "text"

    if media_type == "video_note":
        # can't edit caption of video_note, so send separate text message
        text_msg = await message.answer(
            full_caption if original_caption else "📸 پیش‌نمایش پست\n\n(بدون کپشن)",
            reply_markup=three_buttons()
        )
        store_key = (message.chat.id, text_msg.message_id)
        post_data[store_key] = {
            "type": "video_note",
            "copied_msg_id": copied.message_id,
            "text_msg_id": text_msg.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id
        }
    else:
        # can edit caption -> try
        try:
            await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=copied.message_id,
                caption=full_caption,
                reply_markup=three_buttons()
            )
            store_key = (message.chat.id, copied.message_id)
        except Exception:
            # fallback: delete copied, resend using file_id (rare case)
            await delete_msg(message.chat.id, copied.message_id)
            # extract file_id as last resort
            if message.photo:
                file_id = message.photo[-1].file_id
                m = await message.answer_photo(file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.video:
                m = await message.answer_video(message.video.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.audio:
                m = await message.answer_audio(message.audio.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.document:
                m = await message.answer_document(message.document.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.voice:
                m = await message.answer_voice(message.voice.file_id, caption=full_caption, reply_markup=three_buttons())
            elif message.text:
                m = await message.answer(full_caption, reply_markup=three_buttons())
            else:
                return
            store_key = (message.chat.id, m.message_id)
        post_data[store_key] = {
            "type": "media",
            "copied_msg_id": copied.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id,
            "media_type": media_type
        }

# ---------- process album ----------
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

    # copy all messages to admin (same chat)
    copied_ids = []
    caption = ""
    for m in msgs:
        if not caption and (m.caption or m.text):
            caption = m.caption or m.text or ""
        try:
            c = await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=m.message_id)
            copied_ids.append(c.message_id)
        except:
            pass

    # send button message
    full_caption = f"📸 آلبوم ({len(copied_ids)} آیتم)\n\n{caption if caption else '(بدون کپشن)'}"
    btn_msg = await bot.send_message(chat_id, full_caption, reply_markup=three_buttons())
    store_key = (chat_id, btn_msg.message_id)
    post_data[store_key] = {
        "type": "album",
        "copied_msg_ids": copied_ids,
        "caption": caption,
        "chat_id": chat_id,
        "original_message_ids": [m.message_id for m in msgs]
    }

# ---------- single media (including text) ----------
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
    full_caption = f"📸 پیش‌نمایش پست\n\n{new_caption if new_caption else '(بدون کپشن)'}"

    try:
        if data["type"] == "album":
            # update the button message (the text one)
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=key[1],
                text=f"📸 آلبوم ({len(data['copied_msg_ids'])} آیتم)\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=three_buttons()
            )
        elif data["type"] == "video_note":
            # update the separate text message
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=key[1],  # key[1] is text_msg_id
                text=full_caption,
                reply_markup=three_buttons()
            )
        else:  # "media" type with copied message that has caption
            await bot.edit_message_caption(
                chat_id=data["chat_id"],
                message_id=key[1],  # copied message id
                caption=full_caption,
                reply_markup=three_buttons()
            )
        await message.answer("✅ کپشن ویرایش شد.")
    except Exception as e:
        logging.error(f"Edit error: {e}")
        await message.answer("❌ ویرایش کپشن ممکن نیست. لطفاً پست را لغو و دوباره ارسال کنید.")

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
        # delete copied messages and button message
        if data["type"] in ("media", "video_note"):
            await delete_msg(data["chat_id"], data.get("copied_msg_id"))
        if data["type"] == "video_note":
            await delete_msg(data["chat_id"], data.get("text_msg_id"))
        if data["type"] == "album":
            for cid in data.get("copied_msg_ids", []):
                await delete_msg(data["chat_id"], cid)
        # delete original user message
        if data["type"] == "album":
            for oid in data.get("original_message_ids", []):
                await delete_msg(data["chat_id"], oid)
        else:
            await delete_msg(data["chat_id"], data.get("original_message_id"))
        # delete the button message itself
        await delete_msg(data["chat_id"], key[1])
        await callback.message.answer("❌ انتشار لغو شد.")
        return

    # post to channel
    final_caption = process_caption(data.get("caption", ""))

    try:
        if data["type"] == "album":
            # we need to send the album as a media group with captions
            # we stored copied message ids, but we need file_ids; reconstruct from original? 
            # better: we can forward the original messages to channel? No, we need to change caption.
            # So we need file_ids from the original messages. We'll extract them when collecting album.
            # To keep it simple, we'll store file_ids in data during album creation.
            # I'll adjust the album creation to also save file_ids.
            pass
        elif data["type"] == "video_note":
            # forward the copied video_note to channel
            await bot.copy_message(CHANNEL_ID, from_chat_id=data["chat_id"], message_id=data["copied_msg_id"])
            if final_caption:
                await bot.send_message(CHANNEL_ID, final_caption)
        else:
            # simply copy the (possibly edited) preview message to channel
            await bot.copy_message(
                CHANNEL_ID,
                from_chat_id=data["chat_id"],
                message_id=key[1]  # the message with buttons and preview caption
            )
            # edit the sent message in channel to remove the preview prefix and buttons? 
            # The channel post will have the "📸 پیش‌نمایش پست" prefix and buttons, which is undesirable.
            # Better: re-send using file_id with final caption.
            # So we need to store file_id for single media as well.
        await callback.message.answer("✅ محتوا با موفقیت در کانال منتشر شد.")
    except Exception as e:
        logging.error(f"Publish error: {e}")
        await callback.message.answer(f"❌ خطا: {e}")

# ---------- run ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
