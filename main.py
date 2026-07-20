import asyncio
import os
import re
import time
from typing import List, Optional, Dict

from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message, MessageEntity, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo, CallbackQuery
)

# ═══════════════ تنظیمات از محیط ═══════════════
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = "@spark_news_tel"  # یا شناسه عددی کانال

# لیست کاربران مجاز (از متغیر محیطی یا پیش‌فرض)
ALLOWED_USERS = list(map(int, os.environ.get("ALLOWED_USERS", "8293164271").split(",")))

STATE_TTL = 600  # ثانیه

# ═══════════════ راه‌اندازی ربات ═══════════════
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ═══════════════ FSM ═══════════════
class PostState(StatesGroup):
    waiting_for_caption = State()

# ═══════════════ دکمه‌های پیش‌نمایش ═══════════════
def preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تایید", callback_data="confirm"),
            InlineKeyboardButton(text="✏️ ویرایش", callback_data="edit"),
            InlineKeyboardButton(text="❌ لغو", callback_data="cancel")
        ]
    ])

# ═══════════════ توابع کمکی ═══════════════
def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS

def get_media_type(msg: Message) -> Optional[str]:
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.animation:
        return "animation"
    if msg.document:
        return "document"
    if msg.audio:
        return "audio"
    if msg.voice:
        return "voice"
    if msg.video_note:
        return "video_note"
    return None

def clean_caption(text: str) -> str:
    """حذف @username و لینک‌های http/https از کپشن"""
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    return text.strip()

def build_final_caption(text: Optional[str]) -> str:
    """ساخت کپشن نهایی با لینک کانال"""
    base = clean_caption(text) if text else ""
    suffix = f"\n\n{CHANNEL}"
    if not base:
        return suffix
    return base + suffix

def get_caption_and_entities(msg: Message):
    """استخراج کپشن و entities از پیام"""
    if msg.caption:
        return msg.caption, msg.caption_entities
    if msg.text:
        return msg.text, msg.entities
    return "", None

# ═══════════════ مدیریت آلبوم (ذخیره موقت) ═══════════════
# ساختار: {user_id: {group_id: {"messages": [msg, ...], "task": asyncio.Task}}}
media_group_storage: Dict[int, Dict[str, Dict]] = {}

async def process_media_group(user_id: int, messages: List[Message], state: FSMContext):
    """پردازش آلبوم و نمایش پیش‌نمایش"""
    first = messages[0]
    caption, entities = get_caption_and_entities(first)
    await state.update_data(
        messages=messages,
        caption=caption,
        entities=entities,
        published=False,
        last_activity=time.time()
    )
    await send_preview(user_id, state)

async def delayed_process(user_id: int, group_id: str):
    """تأخیر ۱.۵ ثانیه‌ای برای جمع‌آوری همه‌ی پیام‌های آلبوم"""
    await asyncio.sleep(1.5)
    if user_id not in media_group_storage or group_id not in media_group_storage[user_id]:
        return
    store = media_group_storage[user_id][group_id]
    messages = sorted(store["messages"], key=lambda m: m.message_id)

    # ایجاد یک نمونه جدید از FSMContext برای این کاربر
    state = FSMContext(
        storage=dp.storage,
        key=StorageKey(bot_id=bot.id, user_id=user_id, chat_id=user_id)
    )
    await process_media_group(user_id, messages, state)

    # پاک‌سازی
    del media_group_storage[user_id][group_id]
    if not media_group_storage[user_id]:
        del media_group_storage[user_id]

# ═══════════════ ارسال پیش‌نمایش ═══════════════
async def send_single_media_preview(user_id: int, msg: Message, caption: str, entities, markup):
    """ارسال یک رسانه به‌عنوان پیش‌نمایش"""
    media_type = get_media_type(msg)
    if media_type == "photo":
        return await bot.send_photo(user_id, msg.photo[-1].file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "video":
        return await bot.send_video(user_id, msg.video.file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "animation":
        return await bot.send_animation(user_id, msg.animation.file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "document":
        return await bot.send_document(user_id, msg.document.file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "audio":
        return await bot.send_audio(user_id, msg.audio.file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "voice":
        return await bot.send_voice(user_id, msg.voice.file_id, caption=caption, caption_entities=entities, reply_markup=markup)
    elif media_type == "video_note":
        return await bot.send_video_note(user_id, msg.video_note.file_id, reply_markup=markup)
    return None

def build_media_group_input(messages: List[Message], caption: str, entities) -> List:
    """ساخت ورودی‌های آلبوم برای ارسال هم‌زمان"""
    inputs = []
    for i, msg in enumerate(messages):
        media_type = get_media_type(msg)
        if media_type == "photo":
            file_id = msg.photo[-1].file_id
            if i == 0 and caption:
                inputs.append(InputMediaPhoto(media=file_id, caption=caption, caption_entities=entities))
            else:
                inputs.append(InputMediaPhoto(media=file_id))
        elif media_type == "video":
            file_id = msg.video.file_id
            if i == 0 and caption:
                inputs.append(InputMediaVideo(media=file_id, caption=caption, caption_entities=entities))
            else:
                inputs.append(InputMediaVideo(media=file_id))
    return inputs

async def send_preview(user_id: int, state: FSMContext):
    """حذف پیش‌نمایش قبلی و نمایش پیش‌نمایش جدید"""
    data = await state.get_data()
    old_msg_id = data.get("preview_msg_id")
    if old_msg_id:
        try:
            await bot.delete_message(user_id, old_msg_id)
        except:
            pass

    messages = data["messages"]
    caption = data["caption"]
    entities = data.get("entities")
    kb = preview_keyboard()

    if len(messages) > 1:
        media_inputs = build_media_group_input(messages, caption, entities)
        if not media_inputs:
            await bot.send_message(user_id, "❌ آلبوم خالی است.")
            return
        await bot.send_media_group(user_id, media_inputs)
        preview_msg = await bot.send_message(user_id, "📌 برای انتشار از دکمه‌های زیر استفاده کنید:", reply_markup=kb)
    else:
        msg = messages[0]
        preview_msg = await send_single_media_preview(user_id, msg, caption, entities, kb)

    if preview_msg:
        await state.update_data(preview_msg_id=preview_msg.message_id)

# ═══════════════ هندلر: فوروارد پیام‌ها ═══════════════
@dp.message(F.forward_from | F.forward_from_chat)
async def handle_forward(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    if not is_allowed(user_id):
        return

    # بررسی انقضای جلسه
    data = await state.get_data()
    if data and time.time() - data.get("last_activity", 0) > STATE_TTL:
        await state.clear()
        await msg.answer("⏰ جلسه قبلی منقضی شد. لطفاً دوباره فوروارد کنید.")
        return

    # مدیریت آلبوم
    if msg.media_group_id:
        group_id = msg.media_group_id
        if user_id not in media_group_storage:
            media_group_storage[user_id] = {}
        if group_id not in media_group_storage[user_id]:
            media_group_storage[user_id][group_id] = {"messages": [], "task": None}

        store = media_group_storage[user_id][group_id]
        store["messages"].append(msg)

        if store["task"]:
            store["task"].cancel()
        store["task"] = asyncio.create_task(delayed_process(user_id, group_id))
        await state.update_data(last_activity=time.time())
        return

    # تک پیام
    caption, entities = get_caption_and_entities(msg)
    await state.update_data(
        messages=[msg],
        caption=caption,
        entities=entities,
        published=False,
        last_activity=time.time()
    )
    await send_preview(user_id, state)

# ═══════════════ هندلر: دکمه‌های پیش‌نمایش ═══════════════
@dp.callback_query(F.data.in_({"confirm", "edit", "cancel"}))
async def handle_preview_buttons(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    if not is_allowed(user_id):
        await call.answer("⛔ دسترسی مجاز نیست", show_alert=True)
        return

    await call.answer()
    data = await state.get_data()

    if not data:
        await call.message.edit_text("⛔ داده‌ای یافت نشد. دوباره فوروارد کنید.")
        return

    if call.data == "confirm":
        if data.get("published"):
            await call.message.edit_text("⚠️ این پست قبلاً منتشر شده است.")
            return

        # انتشار
        await state.update_data(published=True)
        messages = data["messages"]
        caption = data["caption"]
        entities = data.get("entities")

        try:
            if len(messages) > 1:
                media_inputs = build_media_group_input(messages, caption, entities)
                if media_inputs:
                    await bot.send_media_group(CHANNEL, media_inputs)
            else:
                msg = messages[0]
                final_caption = build_final_caption(caption)  # کپشن پاک‌شده + لینک کانال
                media_type = get_media_type(msg)
                if media_type == "photo":
                    await bot.send_photo(CHANNEL, msg.photo[-1].file_id, caption=final_caption)
                elif media_type == "video":
                    await bot.send_video(CHANNEL, msg.video.file_id, caption=final_caption)
                elif media_type == "animation":
                    await bot.send_animation(CHANNEL, msg.animation.file_id, caption=final_caption)
                elif media_type == "document":
                    await bot.send_document(CHANNEL, msg.document.file_id, caption=final_caption)
                elif media_type == "audio":
                    await bot.send_audio(CHANNEL, msg.audio.file_id, caption=final_caption)
                elif media_type == "voice":
                    await bot.send_voice(CHANNEL, msg.voice.file_id, caption=final_caption)
                elif media_type == "video_note":
                    await bot.send_video_note(CHANNEL, msg.video_note.file_id)

            # حذف پیام‌های پیش‌نمایش
            try:
                await call.message.delete()
            except:
                pass
            await bot.send_message(user_id, "✅ پست با موفقیت در کانال منتشر شد.")

        except Exception as e:
            await call.message.edit_text(f"❌ خطا در انتشار: {e}")
        finally:
            await state.clear()

    elif call.data == "edit":
        await state.set_state(PostState.waiting_for_caption)
        await call.message.edit_text("✏️ کپشن جدید را به‌صورت یک پیام متنی ارسال کنید.")

    elif call.data == "cancel":
        preview_id = data.get("preview_msg_id")
        if preview_id:
            try:
                await bot.delete_message(user_id, preview_id)
            except:
                pass
        await state.clear()
        await call.message.edit_text("❌ عملیات لغو شد.")

# ═══════════════ هندلر: دریافت کپشن جدید (حالت ویرایش) ═══════════════
@dp.message(PostState.waiting_for_caption)
async def receive_new_caption(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    if not is_allowed(user_id):
        return

    new_caption = msg.text or msg.caption or ""
    try:
        await msg.delete()  # حذف پیام کاربر (اختیاری)
    except:
        pass

    await state.update_data(caption=new_caption, entities=None, last_activity=time.time())
    # دوباره پیش‌نمایش را نشان می‌دهیم (حالت FSM همچنان active است)
    try:
        await send_preview(user_id, state)
    except Exception as e:
        await bot.send_message(user_id, f"❌ خطا در نمایش پیش‌نمایش: {e}")
    # لازم نیست state را پاک کنیم چون کاربر می‌تواند دوباره ویرایش کند یا تایید کند

# ═══════════════ راه‌اندازی ═══════════════
async def main():
    print("🤖 ربات در حال اجرا است...")
    # پاک کردن Webhook برای اطمینان از دریافت آپدیت‌ها از طریق polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
