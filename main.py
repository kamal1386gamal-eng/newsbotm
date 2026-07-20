# تابع کمکی: ارسال پیش‌نمایش با مدیا (فقط برای fallback)
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


# نسخه اصلاح‌شده handle_text_for_edit
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
        media_type = data["media_type"]
        caption_text = new_caption if new_caption else '(بدون کپشن)'
        full_caption = f"📸 پیش‌نمایش پست\n\n{caption_text}"

        # تلاش برای ویرایش مستقیم کپشن (برای مدیاهایی که اجازه می‌دن)
        if media_type in ("photo", "video", "audio", "document", "voice"):
            try:
                await bot.edit_message_caption(
                    chat_id=data["main_chat_id"],
                    message_id=data["main_message_id"],
                    caption=full_caption,
                    reply_markup=preview_keyboard()
                )
                await message.answer("✅ کپشن با موفقیت ویرایش شد.")
                return
            except Exception as e:
                logging.warning(f"ویرایش مستقیم کپشن ممکن نبود: {e}")
                # اگر نشد، به fallback می‌رویم

        # حذف پیش‌نمایش قدیمی (برای video_note، آلبوم یا در صورت خطا)
        await delete_preview_messages(data["main_chat_id"], data["main_message_id"], data.get("extra_message_id"))
        del preview_data[store_key]   # حذف کلید قدیمی

        if media_type == "album":
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
            ids = await send_media_preview(message, media_type, data["media_data"], new_caption)
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
