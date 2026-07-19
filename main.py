import asyncio
import time
import os
from typing import List, Optional
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, MessageEntity, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo, CallbackQuery
)

# ═══════════════ تنظیمات ═══════════════
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = "@spark_news_tel"
ALLOWED_USERS = [8293164271]          # آیدی عددی کاربران مجاز
STATE_TTL = 600                       # ۱۰ دقیقه انقضا

# ═══════════════ ربات و ذخیره‌سازی ═══════════════
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ═══════════════ FSM ═══════════════
class PostState(StatesGroup):
    waiting_for_caption = State()

# ═══════════════ دکمه‌ها ═══════════════
def preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تایید", callback_data="confirm"),
            InlineKeyboardButton(text="✏️ ویرایش", callback_data="edit"),
            InlineKeyboardButton(text="❌ لغو", callback_data="cancel")
        ]
    ])

# ═══════════════ ابزارهای کمکی ═══════════════
def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS

def get_media_type(msg: Message) -> Optional[str]:
    if msg.photo: return "photo"
    if msg.video: return "video"
    if msg.animation: return "animation"
    if msg.document: return "document"
    if msg.audio: return "audio"
    if msg.voice: return "voice"
    if msg.video_note: return "video_note"
    return None

def build_caption(text: Optional[str], entities: Optional[List[MessageEntity]]):
    """کپشن نهایی = کپشن اصلی + آیدی کانال"""
    base = text or ""
    suffix = f"\n\n{CHANNEL}"
    if not base:
        return suffix, None
    return base + suffix, entities

def build_media_group_input(messages: List[Message], caption: Optional[str] = None, entities=None) -> List:
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

# ═══════════════ ارسال پیش‌نمایش ═══════════════
async def send_single_media_preview(user_id: int, msg: Message, caption: str, entities, markup):
    """ارسال پیش‌نمایش برای یک فایل (غیر آلبومی)"""
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

async def send_preview(user_id: int, state: FSMContext):
    """ساخت یا بازسازی پیش‌نمایش، حذف قبلی اگر وجود داشت"""
    data = await state.get_data()
    # حذف پیش‌نمایش قبلی
    old_msg_id = data.get("preview_msg_id")
    if old_msg_id:
        try: await bot.delete_message(user_id, old_msg_id)
        except: pass

    messages = data["messages"]
    caption = data["caption"]
    entities = data.get("entities")
    kb = preview_keyboard()

    if len(messages) > 1:  # آلبوم
        media_inputs = build_media_group_input(messages, caption, entities)
        if not media_inputs:
            raise ValueError("آلبوم خالی است")
        await bot.send_media_group(user_id, media_inputs)
        # دکمه‌ها در پیام جداگانه
        preview_msg = await bot.send_message(user_id, "برای انتشار از دکمه‌های زیر استفاده کنید:", reply_markup=kb)
    else:  # تک فایل
        msg = messages[0]
        preview_msg = await send_single_media_preview(user_id, msg, caption, entities, kb)

    if preview_msg:
        await state.update_data(preview_msg_id=preview_msg.message_id)

# ═══════════════ مدیریت آلبوم (Media Group) ═══════════════
MEDIA_GROUP_STORAGE = {}  # نگهداری موقت پیام‌های group

async def process_media_group(user_id: int, messages: List[Message], state: FSMContext):
    """پس از جمع‌آوری کامل آلبوم"""
    # کپشن از اولین پیام
    first = messages[0]
    caption = first.caption or first.text or ""
    entities = first.caption_entities if first.caption else first.entities
    await state.update_data(
        messages=messages,
        caption=caption,
        entities=entities,
        published=False,
        last_activity=time.time()
    )
    await send_preview(user_id, state)

async def _delayed_process(user_id: int, group_id: str):
    await asyncio.sleep(1.5)
    if user_id not in MEDIA_GROUP_STORAGE or group_id not in MEDIA_GROUP_STORAGE[user_id]:
        return
    store = MEDIA_GROUP_STORAGE[user_id][group_id]
    messages = sorted(store["messages"], key=lambda m: m.message_id)

    # ساخت FSMContext برای این کاربر
    state = FSMContext(
        storage=dp.storage,
        key=StorageKey(bot_id=bot.id, user_id=user_id, chat_id=user_id)
    )
    await process_media_group(user_id, messages, state)

    # پاکسازی
    del MEDIA_GROUP_STORAGE[user_id][group_id]
    if not MEDIA_GROUP_STORAGE[user_id]:
        del MEDIA_GROUP_STORAGE[user_id]

# ═══════════════ Handler: دریافت فوروارد ═══════════════
@dp.message(F.forward_from | F.forward_from_chat)
async def handle_forward(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return

    # پاکسازی خودکار در صورت انقضا
    data = await state.get_data()
    if data and time.time() - data.get("last_activity", 0) > STATE_TTL:
        await state.clear()
        await msg.answer("⏰ جلسه قبلی به دلیل عدم فعالیت لغو شد. لطفاً دوباره ارسال کنید.")
        return

    user_id = msg.from_user.id

    # اگر بخشی از یک آلبوم است
    if msg.media_group_id:
        group_id = msg.media_group_id
        if user_id not in MEDIA_GROUP_STORAGE:
            MEDIA_GROUP_STORAGE[user_id] = {}
        if group_id not in MEDIA_GROUP_STORAGE[user_id]:
            MEDIA_GROUP_STORAGE[user_id][group_id] = {"messages": [], "task": None}

        store = MEDIA_GROUP_STORAGE[user_id][group_id]
        store["messages"].append(msg)

        if store["task"]:
            store["task"].cancel()
        store["task"] = asyncio.create_task(_delayed_process(user_id, group_id))
        await state.update_data(last_activity=time.time())
        return

    # پیام تکی
    caption = msg.caption or msg.text or ""
    entities = msg.caption_entities if msg.caption else msg.entities
    await state.update_data(
        messages=[msg],
        caption=caption,
        entities=entities,
        published=False,
        last_activity=time.time()
    )
    await send_preview(user_id, state)

# ═══════════════ Handler: دکمه‌های تأیید / ویرایش / لغو ═══════════════
@dp.callback_query(F.data.in_({"confirm", "edit", "cancel"}))
async def handle_buttons(call: CallbackQuery, state: FSMContext):
    if not is_allowed(call.from_user.id):
        await call.answer("⛔ دسترسی مجاز نیست", show_alert=True)
        return

    await call.answer()
    user_id = call.from_user.id
    data = await state.get_data()

    if not data:
        await call.message.edit_text("⛔ داده‌ای یافت نشد.")
        return

    # ── تأیید ──
    if call.data == "confirm":
        if data.get("published"):
            await call.message.edit_text("⚠️ این پست قبلاً منتشر شده است.")
            return
        await state.update_data(published=True)

        messages = data["messages"]
        caption = data["caption"]
        entities = data.get("entities")

        try:
            if len(messages) > 1:  # آلبوم
                media_inputs = build_media_group_input(messages, caption, entities)
                if media_inputs:
                    await bot.send_media_group(CHANNEL, media_inputs)
            else:
                msg = messages[0]
                final_caption, ent = build_caption(caption, entities)
                media_type = get_media_type(msg)
                if media_type == "photo":
                    await bot.send_photo(CHANNEL, msg.photo[-1].file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "video":
                    await bot.send_video(CHANNEL, msg.video.file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "animation":
                    await bot.send_animation(CHANNEL, msg.animation.file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "document":
                    await bot.send_document(CHANNEL, msg.document.file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "audio":
                    await bot.send_audio(CHANNEL, msg.audio.file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "voice":
                    await bot.send_voice(CHANNEL, msg.voice.file_id, caption=final_caption, caption_entities=ent)
                elif media_type == "video_note":
                    await bot.send_video_note(CHANNEL, msg.video_note.file_id)
            # پاک کردن پیام پیش‌نمایش
            try: await call.message.delete()
            except: pass
            await bot.send_message(user_id, "✅ پست با موفقیت منتشر شد.")
        except Exception as e:
            await call.message.edit_text(f"❌ خطا در انتشار: {e}")
        finally:
            await state.clear()

    # ── ویرایش ──
    elif call.data == "edit":
        await state.set_state(PostState.waiting_for_caption)
        await call.message.edit_text("✏️ کپشن جدید را ارسال کنید.")

    # ── لغو ──
    elif call.data == "cancel":
        # حذف پیش‌نمایش
        preview_id = data.get("preview_msg_id")
        if preview_id:
            try: await bot.delete_message(user_id, preview_id)
            except: pass
        await state.clear()
        await call.message.edit_text("❌ عملیات لغو شد.")

# ═══════════════ Handler: دریافت کپشن جدید ═══════════════
from aiogram.fsm.storage.base import StorageKey  # برای ساخت کلید در بالا استفاده شده بود، ولی اینجا هم نیاز داریم

@dp.message(PostState.waiting_for_caption)
async def receive_new_caption(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return

    user_id = msg.from_user.id
    new_caption = msg.text or msg.caption or ""
    # حذف پیام کاربر
    try: await msg.delete()
    except: pass

    await state.update_data(caption=new_caption, entities=None, last_activity=time.time())
    await state.set_state(PostState.waiting_for_caption)  # همون وضعیت (برای جلوگیری از ورود دوباره بدون فوروارد)
    try:
        await send_preview(user_id, state)
    except Exception as e:
        await bot.send_message(user_id, f"❌ خطا در نمایش پیش‌نمایش: {e}")

# ═══════════════ راه‌اندازی ═══════════════
async def main():
    print("🤖 Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
