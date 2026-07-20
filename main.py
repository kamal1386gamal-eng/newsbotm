@dp.callback_query(F.data.in_(["post", "cancel_post"]))
async def handle_post_or_cancel(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id): return
    await callback.answer()
    key = (callback.message.chat.id, callback.message.message_id)
    data = post_data.pop(key, None)
    if not data:
        await callback.message.answer("⚠️ پست یافت نشد.")
        return

    # ----- لغو -----
    if callback.data == "cancel_post":
        await callback.message.answer("❌ انتشار لغو شد.")
        # پاک‌سازی
        for msg_id in data.get("clean_msg_ids", []):
            await delete_msg(data["chat_id"], msg_id)
        if data["type"] == "video_note":
            await delete_msg(data["chat_id"], data["vn_copied_id"])
            await delete_msg(data["chat_id"], data["text_msg_id"])
        elif data["type"] == "album":
            for cid in data.get("copied_msg_ids", []):
                await delete_msg(data["chat_id"], cid)
            await delete_msg(data["chat_id"], data["btn_msg_id"])
        else:
            await delete_msg(data["chat_id"], data["copied_msg_id"])
        if data["type"] == "album":
            for oid in data.get("original_message_ids", []):
                await delete_msg(data["chat_id"], oid)
        else:
            await delete_msg(data["chat_id"], data.get("original_message_id"))
        return   # توقف کامل، هیچ ارسالی انجام نمی‌شود

    # ----- انتشار -----
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
            await bot.copy_message(CHANNEL_ID, from_chat_id=data["chat_id"], message_id=data["original_message_id"])
            if final_caption:
                await bot.send_message(CHANNEL_ID, final_caption)
        elif data["type"] == "text":
            if final_caption:
                await bot.send_message(CHANNEL_ID, final_caption)
            else:
                await bot.send_message(CHANNEL_ID, " ")
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
        post_data[key] = data
        return

    # پاک‌سازی پس از انتشار موفق
    for msg_id in data.get("clean_msg_ids", []):
        await delete_msg(data["chat_id"], msg_id)
    if data["type"] == "video_note":
        await delete_msg(data["chat_id"], data["vn_copied_id"])
        await delete_msg(data["chat_id"], data["text_msg_id"])
    elif data["type"] == "album":
        for cid in data.get("copied_msg_ids", []):
            await delete_msg(data["chat_id"], cid)
        await delete_msg(data["chat_id"], data["btn_msg_id"])
    else:
        await delete_msg(data["chat_id"], data["copied_msg_id"])
    if data["type"] == "album":
        for oid in data.get("original_message_ids", []):
            await delete_msg(data["chat_id"], oid)
    else:
        await delete_msg(data["chat_id"], data.get("original_message_id"))
