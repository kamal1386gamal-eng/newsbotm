import os
import re
import asyncio
import logging
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InputMediaPhoto, InputMediaVideo

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")

CHANNEL_ID = os.getenv("CHANNEL_ID", "@spark_news_tel")
ALLOWED_USER_ID = 8293164271

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ذخیره‌سازی پست‌های فعال
post_data: Dict[tuple, Dict[str, Any]] = {}
# نگهداری کاربرانی که در حال ویرایش کپشن هستند
edit_state: Dict[int, tuple] = {}
# بافر آلبوم‌ها و تایمر مربوطه
album_buffer: Dict[str, Dict[str, Any]] = {}

def is_allowed(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def process_caption(caption: str) -> str:
    if not caption:
        caption = ""
    # اولین لینک را با آیدی کانال جایگزین کن
    if re.search(r"https?://\S+", caption):
        caption = re.sub(r"https?://\S+", "@spark_news_tel", caption, count=1)
    # سایر لینک‌ها و منشن‌ها و هشتگ‌ها را حذف کن
    caption = re.sub(r"https?://\S+", "", caption)
    caption = re.sub(r"@(?!spark_news_tel\b)\w+", "", caption)
    caption = re.sub(r"#\w+", "", caption)
    # اطمینان از وجود آیدی کانال
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
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

# ---------- تابع ارسال پیش‌نمایش نهایی (بدون دکمه) ----------
async def send_clean_preview(chat_id: int, data: Dict, final_caption: str):
    """
    پیش‌نمایش نهایی را می‌فرستد و شناسه پیام‌های ارسالی را در data ذخیره می‌کند.
    """
    try:
        if data["type"] == "album":
            media_list = []
            for idx, item in enumerate(data["items"]):
                cap = final_caption if idx == 0 else ""
                if item["type"] == "photo":
                    media_list.append(InputMediaPhoto(media=item["file_id"], caption=cap))
                else:
                    media_list.append(InputMediaVideo(
                        media=item["file_id"],
                        caption=cap,
                        duration=item.get("duration"),
                        width=item.get("width"),
                        height=item.get("height")
                    ))
            sent = await bot.send_media_group(chat_id, media=media_list)
            # ذخیره شناسه اولین پیام گروه (یا همه) برای حذف بعدی
            data["clean_msg_ids"] = [m.message_id for m in sent]
        elif data["type"] == "video_note":
            # کپی ویدئو نوت
            copied = await bot.copy_message(chat_id, from_chat_id=data["chat_id"],
                                            message_id=data["original_message_id"])
            msg_ids = [copied.message_id]
            if final_caption:
                cap_msg = await bot.send_message(chat_id, final_caption)
                msg_ids.append(cap_msg.message_id)
            data["clean_msg_ids"] = msg_ids
        elif data["type"] == "text":
            if not final_caption:
                final_caption = " "  # جلوگیری از خطای ارسال خالی
            msg = await bot.send_message(chat_id, final_caption)
            data["clean_msg_ids"] = [msg.message_id]
        else:
            file_id = data.get("file_id")
            if not file_id:
                # کپی کل پیام اصلی
                copied = await bot.copy_message(chat_id, from_chat_id=data["chat_id"],
                                                message_id=data["original_message_id"])
                data["clean_msg_ids"] = [copied.message_id]
            else:
                media_type = data.get("media_type")
                if media_type == "photo":
                    sent = await bot.send_photo(chat_id, file_id, caption=final_caption)
                elif media_type == "video":
                    sent = await bot.send_video(chat_id, file_id, caption=final_caption)
                elif media_type == "audio":
                    sent = await bot.send_audio(chat_id, file_id, caption=final_caption)
                elif media_type == "document":
                    sent = await bot.send_document(chat_id, file_id, caption=final_caption)
                elif media_type == "voice":
                    sent = await bot.send_voice(chat_id, file_id, caption=final_caption)
                else:
                    return
                data["clean_msg_ids"] = [sent.message_id]
    except Exception as e:
        logging.warning(f"Failed to send clean preview: {e}")

# ---------- ساخت پیش‌نمایش تک‌رسانه ----------
async def create_single_preview(message: types.Message):
    original_caption = message.caption or message.text or ""
    full_caption = f"📸 پیش‌نمایش پست\n\n{original_caption}"

    # تلاش برای کپی پیام اصلی
    try:
        copied = await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception as e:
        logging.warning(f"copy_message failed: {e}, using fallback send method")
        copied = None

    # حالت ویدئو نوت
    if message.video_note:
        if copied is None:
            await message.answer("⚠️ امکان کپی ویدئو نوت وجود ندارد. لطفاً خود پیام را مستقیماً ارسال کنید.")
            return
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
            "original_message_id": message.message_id,
            "clean_msg_ids": []  # هنوز پیش‌نمایش تمیزی ارسال نشده
        }
        return

    # متن ساده
    if message.text and not (message.photo or message.video or message.audio or message.document or message.voice):
        if copied is None:
            new_msg = await message.answer(full_caption, reply_markup=three_buttons())
            copied = new_msg
        else:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=copied.message_id,
                    text=full_caption,
                    reply_markup=three_buttons()
                )
            except Exception:
                await delete_msg(message.chat.id, copied.message_id)
                new_msg = await message.answer(full_caption, reply_markup=three_buttons())
                copied = new_msg
        store_key = (message.chat.id, copied.message_id)
        post_data[store_key] = {
            "type": "text",
            "copied_msg_id": copied.message_id,
            "caption": original_caption,
            "chat_id": message.chat.id,
            "original_message_id": message.message_id,
            "clean_msg_ids": []
        }
        return

    # رسانه‌های عکس، ویدئو، صدا و...
    file_id = None
    media_type = None

    if copied is None:
        # کپی نشد، با file_id می‌فرستیم
        if message.photo:
            m = await message.answer_photo(message.photo[-1].file_id, caption=full_caption, reply_markup=three_buttons())
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.video:
            m = await message.answer_video(message.video.file_id, caption=full_caption, reply_markup=three_buttons())
            file_id = message.video.file_id
            media_type = "video"
        elif message.audio:
            m = await message.answer_audio(message.audio.file_id, caption=full_caption, reply_markup=three_buttons())
            file_id = message.audio.file_id
            media_type = "audio"
        elif message.document:
            m = await message.answer_document(message.document.file_id, caption=full_caption, reply_markup=three_buttons())
            file_id = message.document.file_id
            media_type = "document"
        elif message.voice:
            m = await message.answer_voice(message.voice.file_id, caption=full_caption, reply_markup=three_buttons())
            file_id = message.voice.file_id
            media_type = "voice"
        else:
            await message.answer("⚠️ نوع فایل پشتیبانی نمی‌شود.")
            return
        copied = m
    else:
        # کپی موفق، سعی در ویرایش کپشن
        try:
            await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=copied.message_id,
                caption=full_caption,
                reply_markup=three_buttons()
            )
        except Exception as e:
            logging.warning(f"edit_message_caption failed: {e}, using fallback")
            await delete_msg(message.chat.id, copied.message_id)
            if message.photo:
                m = await message.answer_photo(message.photo[-1].file_id, caption=full_caption, reply_markup=three_buttons())
                file_id = message.photo[-1].file_id
                media_type = "photo"
            elif message.video:
                m = await message.answer_video(message.video.file_id, caption=full_caption, reply_markup=three_buttons())
                file_id = message.video.file_id
                media_type = "video"
            elif message.audio:
                m = await message.answer_audio(message.audio.file_id, caption=full_caption, reply_markup=three_buttons())
                file_id = message.audio.file_id
                media_type = "audio"
            elif message.document:
                m = await message.answer_document(message.document.file_id, caption=full_caption, reply_markup=three_buttons())
                file_id = message.document.file_id
                media_type = "document"
            elif message.voice:
                m = await message.answer_voice(message.voice.file_id, caption=full_caption, reply_markup=three_buttons())
                file_id = message.voice.file_id
                media_type = "voice"
            else:
                return
            copied = m
        else:
            # ویرایش موفق، file_id را استخراج کن
            if message.photo:
                file_id = message.photo[-1].file_id
                media_type = "photo"
            elif message.video:
                file_id = message.video.file_id
                media_type = "video"
            elif message.audio:
                file_id = message.audio.file_id
                media_type = "audio"
            elif message.document:
                file_id = message.document.file_id
                media_type = "document"
            elif message.voice:
                file_id = message.voice.file_id
                media_type = "voice"

    store_key = (message.chat.id, copied.message_id)
    post_data[store_key] = {
        "type": "media",
        "copied_msg_id": copied.message_id,
        "caption": original_caption,
        "chat_id": message.chat.id,
        "original_message_id": message.message_id,
        "file_id": file_id,
        "media_type": media_type,
        "clean_msg_ids": []
    }

# ---------- مدیریت آلبوم با تایمر بهبودیافته ----------
async def start_album_timer(gid: str, chat_id: int):
    """تایمر ۱.۵ ثانیه‌ای برای جمع‌آوری آلبوم، با قابلیت لغو با آمدن بخش جدید"""
    await asyncio.sleep(1.5)
    # بعد از اتمام تایمر، اگر هنوز گروه وجود دارد پردازش کن
    buf = album_buffer.get(gid)
    if buf:
        await process_album(gid, chat_id)

@dp.message(F.media_group_id)
async def on_album_part(message: types.Message):
    if not is_allowed(message.from_user.id): return
    # در صورت دریافت رسانه جدید، حالت ویرایش کپشن قبلی را لغو کن
    edit_state.pop(message.from_user.id, None)

    gid = message.media_group_id
    if gid not in album_buffer:
        album_buffer[gid] = {"messages": [], "timer": None}
    buf = album_buffer[gid]
    buf["messages"].append(message)

    # اگر تایمری در حال اجراست لغو کن و تایمر جدید بساز
    if buf["timer"] and not buf["timer"].done():
        buf["timer"].cancel()
    buf["timer"] = asyncio.create_task(start_album_timer(gid, message.chat.id))

async def process_album(gid: str, chat_id: int):
    buf = album_buffer.pop(gid, None)
    if not buf: return
    msgs: List[types.Message] = buf["messages"]
    msgs.sort(key=lambda m: m.message_id)

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
            continue
        if not caption and (m.caption or m.text):
            caption = m.caption or m.text or ""
        try:
            c = await bot.copy_message(chat_id=chat_id, from_chat_id=chat_id, message_id=m.message_id)
            copied_ids.append(c.message_id)
        except Exception as e:
            logging.warning(f"Failed to copy album part: {e}")

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
        "original_message_ids": [m.message_id for m in msgs],
        "clean_msg_ids": []
    }

# ---------- دریافت تک‌رسانه ----------
@dp.message(F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.text, ~F.media_group_id)
async def handle_single(message: types.Message):
    if not is_allowed(message.from_user.id): return
    # هر محتوای جدید حالت ویرایش را خاتمه می‌دهد
    edit_state.pop(message.from_user.id, None)
    await create_single_preview(message)

# ---------- ویرایش کپشن ----------
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
    final_caption = process_caption(new_caption)

    # حذف پیش‌نمایش تمیز قبلی اگر وجود داشت
    for old_msg_id in data.get("clean_msg_ids", []):
        await delete_msg(data["chat_id"], old_msg_id)
    data["clean_msg_ids"] = []

    # ویرایش پیام اصلی پیش‌نمایش با دکمه‌ها
    try:
        if data["type"] == "album":
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=data["btn_msg_id"],
                text=f"📸 آلبوم ({len(data['items'])} آیتم)\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                reply_markup=three_buttons()
            )
        elif data["type"] == "video_note":
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
        else:
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
        # بازگرداندن حالت ویرایش برای تلاش دوباره
        edit_state[uid] = key
        return

    # ارسال پیش‌نمایش تمیز جدید
    await send_clean_preview(data["chat_id"], data, final_caption)

# ---------- انتشار یا لغو ----------
@dp.callback_query(F.data.in_(["post", "cancel_post"]))
async def handle_post_or_cancel(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    key = (callback.message.chat.id, callback.message.message_id)
    data = post_data.pop(key, None)
    if not data:
        await callback.message.answer("⚠️ پست یافت نشد.")
        return

    final_caption = process_caption(data.get("caption", ""))

    if callback.data == "post":
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
                await bot.copy_message(CHANNEL_ID, from_chat_id=data["chat_id"], message_id=data["original_message_id"])
                if final_caption:
                    await bot.send_message(CHANNEL_ID, final_caption)
            elif data["type"] == "text":
                if final_caption:
                    await bot.send_message(CHANNEL_ID, final_caption)
                else:
                    await bot.send_message(CHANNEL_ID, " ")  # جلوگیری از خطا
            else:
                file_id = data.get("file_id")
                media_type = data.get("media_type")
                if file_id and media_type:
                    if media_type == "photo":
                        await bot.send_photo(CHANNEL_ID, file_id, caption=final_caption)
                    elif media_type == "video":
                        await bot.send_video(CHANNEL_ID, file_id, caption=final_caption)
                    elif media_type == "audio":
                        await bot.send_audio(CHANNEL_ID, file_id, caption=final_caption)
                    elif media_type == "document":
                        await bot.send_document(CHANNEL_ID, file_id, caption=final_caption)
                    elif media_type == "voice":
                        await bot.send_voice(CHANNEL_ID, file_id, caption=final_caption)
                else:
                    await bot.copy_message(CHANNEL_ID, from_chat_id=data["chat_id"], message_id=data["original_message_id"])
            await callback.message.answer("✅ محتوا با موفقیت در کانال منتشر شد.")
        except Exception as e:
            logging.error(f"Publish error: {e}")
            await callback.message.answer(f"❌ خطا در انتشار: {e}")
            post_data[key] = data  # بازگردانی
            return
    else:
        await callback.message.answer("❌ انتشار لغو شد.")

    # پاک‌سازی همه پیام‌های پیش‌نمایش (دکمه‌دار و تمیز) و پیام‌های اصلی
    # پیش‌نمایش تمیز
    for msg_id in data.get("clean_msg_ids", []):
        await delete_msg(data["chat_id"], msg_id)

    # پیش‌نمایش دکمه‌دار و کپی‌ها
    if data["type"] == "video_note":
        await delete_msg(data["chat_id"], data["vn_copied_id"])
        await delete_msg(data["chat_id"], data["text_msg_id"])
    elif data["type"] == "album":
        for cid in data.get("copied_msg_ids", []):
            await delete_msg(data["chat_id"], cid)
        await delete_msg(data["chat_id"], data["btn_msg_id"])
    else:
        await delete_msg(data["chat_id"], data["copied_msg_id"])

    # پیام‌های اصلی کاربر
    if data["type"] == "album":
        for oid in data.get("original_message_ids", []):
            await delete_msg(data["chat_id"], oid)
    else:
        await delete_msg(data["chat_id"], data.get("original_message_id"))

@dp.message()
async def fallback(message: types.Message):
    if is_allowed(message.from_user.id):
        await message.answer("لطفاً یک عکس، فیلم، فایل، آلبوم یا متن ارسال کنید.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
