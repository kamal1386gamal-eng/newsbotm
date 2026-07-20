# تابع کمکی برای ارسال پیش‌نمایش با مدیا (برای استفاده هم در create_preview و هم ویرایش)
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

# تابع create_preview رو هم با send_media_preview بازنویسی می‌کنیم تا یکسان باشه
async def create_preview(original_message: types.Message, media_type: str, media_data: dict, caption: str, album: bool = False):
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

# حالا handle_text_for_edit رو کامل عوض می‌کنیم:
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
