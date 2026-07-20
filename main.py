# اضافه کردن import مورد نیاز
from aiogram.types import InputMediaPhoto, InputMediaVideo

# تابع کمکی برای ارسال پیش‌نمایش نهایی
async def send_clean_preview(chat_id: int, data: Dict, final_caption: str):
    """Send a final preview of the post (without extra text/buttons) to the admin chat."""
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
            await bot.send_media_group(chat_id, media=media_list)
        elif data["type"] == "video_note":
            # ویدئو نوت را کپی می‌کنیم و سپس کپشن را جدا ارسال می‌کنیم
            await bot.copy_message(chat_id, from_chat_id=data["chat_id"], message_id=data["original_message_id"])
            if final_caption:
                await bot.send_message(chat_id, final_caption)
        elif data["type"] == "text":
            await bot.send_message(chat_id, final_caption)
        else:  # media with caption (photo, video, audio, document, voice)
            copied = await bot.copy_message(chat_id, from_chat_id=data["chat_id"], message_id=data["original_message_id"])
            await bot.edit_message_caption(chat_id, copied.message_id, caption=final_caption)
    except Exception as e:
        logging.warning(f"Failed to send clean preview: {e}")

# تغییر در handle_new_caption
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
    final_caption = process_caption(new_caption)  # کپشن نهایی برای کانال

    # به‌روزرسانی پیش‌نمایش موجود (با دکمه‌ها و پیشوند)
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
        return

    # ارسال پیش‌نمایش نهایی (بدون دکمه و بدون پیشوند)
    await send_clean_preview(data["chat_id"], data, final_caption)
