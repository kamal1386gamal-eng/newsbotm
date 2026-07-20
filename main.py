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
    final_caption = process_caption(new_caption)   # همین کپشن نهایی که به کانال می‌رود

    # حذف پیش‌نمایش‌های تمیز قبلی (اگر وجود داشته)
    for old_msg_id in data.get("clean_msg_ids", []):
        await delete_msg(data["chat_id"], old_msg_id)
    data["clean_msg_ids"] = []

    # تلاش برای ویرایش همان پیش‌نمایش دکمه‌دار (عکس/ویدئو/آلبوم/متن)
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
            # عکس، ویدئو، فایل و... → ویرایش کپشن روی همان پیام
            await bot.edit_message_caption(
                chat_id=data["chat_id"],
                message_id=data["copied_msg_id"],
                caption=full_preview,
                reply_markup=three_buttons()
            )
        await message.answer("✅ کپشن ویرایش شد.")
    except Exception as e:
        logging.warning(f"Edit failed, rebuilding preview: {e}")
        # ویرایش نشد → پیام قبلی را حذف می‌کنیم و یک پیام نو با عکس و دکمه می‌سازیم
        chat_id = data["chat_id"]

        # پاک کردن پیش‌نمایش قبلی
        if data["type"] == "album":
            await delete_msg(chat_id, data["btn_msg_id"])
        elif data["type"] == "video_note":
            await delete_msg(chat_id, data["text_msg_id"])
        elif data["type"] == "text":
            await delete_msg(chat_id, data["copied_msg_id"])
        else:
            await delete_msg(chat_id, data["copied_msg_id"])

        # ساخت مجدد پیش‌نمایش
        try:
            if data["type"] == "album":
                new_btn = await bot.send_message(
                    chat_id,
                    f"📸 آلبوم ({len(data['items'])} آیتم)\n\n{new_caption if new_caption else '(بدون کپشن)'}",
                    reply_markup=three_buttons()
                )
                new_key = (chat_id, new_btn.message_id)
                post_data[new_key] = data
                data["btn_msg_id"] = new_btn.message_id
                del post_data[key]

            elif data["type"] == "video_note":
                new_text = await bot.send_message(chat_id, full_preview, reply_markup=three_buttons())
                new_key = (chat_id, new_text.message_id)
                post_data[new_key] = data
                data["text_msg_id"] = new_text.message_id
                del post_data[key]

            elif data["type"] == "text":
                new_msg = await bot.send_message(chat_id, full_preview, reply_markup=three_buttons())
                new_key = (chat_id, new_msg.message_id)
                post_data[new_key] = data
                data["copied_msg_id"] = new_msg.message_id
                del post_data[key]

            else:  # رسانه (عکس، ویدئو، ...)
                file_id = data.get("file_id")
                media_type = data.get("media_type")
                if file_id and media_type:
                    if media_type == "photo":
                        new_msg = await bot.send_photo(chat_id, file_id, caption=full_preview, reply_markup=three_buttons())
                    elif media_type == "video":
                        new_msg = await bot.send_video(chat_id, file_id, caption=full_preview, reply_markup=three_buttons())
                    elif media_type == "audio":
                        new_msg = await bot.send_audio(chat_id, file_id, caption=full_preview, reply_markup=three_buttons())
                    elif media_type == "document":
                        new_msg = await bot.send_document(chat_id, file_id, caption=full_preview, reply_markup=three_buttons())
                    elif media_type == "voice":
                        new_msg = await bot.send_voice(chat_id, file_id, caption=full_preview, reply_markup=three_buttons())
                    else:
                        await message.answer("❌ نوع رسانه پشتیبانی نمی‌شود.")
                        return
                    new_key = (chat_id, new_msg.message_id)
                    post_data[new_key] = data
                    data["copied_msg_id"] = new_msg.message_id
                    del post_data[key]
                else:
                    # file_id نداریم، پیام اصلی را دوباره کپی می‌کنیم
                    new_copy = await bot.copy_message(
                        chat_id,
                        from_chat_id=data["chat_id"],
                        message_id=data["original_message_id"],
                        caption=full_preview,
                        reply_markup=three_buttons()
                    )
                    new_key = (chat_id, new_copy.message_id)
                    post_data[new_key] = data
                    data["copied_msg_id"] = new_copy.message_id
                    del post_data[key]

            await message.answer("✅ کپشن ویرایش شد و پیش‌نمایش بازسازی گردید.")
        except Exception as rebuild_error:
            logging.error(f"Rebuild failed: {rebuild_error}")
            await message.answer("❌ متأسفانه نتوانستم پیش‌نمایش جدید را بسازم. لطفاً پست را لغو و دوباره ارسال کنید.")
            # داده را برنمی‌گردانیم تا از کار افتاده شود
            return

    # دیگر send_clean_preview صدا زده نمی‌شود! فقط همان پیش‌نمایش دارای دکمه باقی می‌ماند.
