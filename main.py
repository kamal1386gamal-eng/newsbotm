import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes

# تنظیمات لاگ
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================
# دریافت تنظیمات از محیط (Environment Variables)
# ========================
TOKEN = os.getenv("BOT_TOKEN")  # توکن را از Railway یا محیط دریافت کن
if not TOKEN:
    raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است!")

CHANNEL_ID = "@spark_news_tel"  # شناسه کانال مقصد

# حالات مکالمه
WAITING_FORWARD, CONFIRMING = range(2)

# دیکشنری برای ذخیره‌ی موقت اطلاعات عکس هر کاربر
user_data_store = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """فرمان /start"""
    await update.message.reply_text(
        "سلام! 👋\n"
        "یک عکس را به من فوروارد کنید تا پس از تأیید شما، آن را در کانال منتشر کنم.\n"
        "برای لغو در هر مرحله، دستور /cancel را بفرستید."
    )
    return WAITING_FORWARD


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو عملیات"""
    user_id = update.effective_user.id
    user_data_store.pop(user_id, None)
    await update.message.reply_text("❌ عملیات لغو شد.")
    return ConversationHandler.END


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت عکس فورواردی"""
    user = update.effective_user
    message = update.message

    # بررسی وجود عکس
    if not message.photo:
        await message.reply_text("لطفاً یک عکس فوروارد کنید (یا یک عکس معمولی بفرستید).")
        return WAITING_FORWARD

    # ذخیره اطلاعات عکس
    user_data_store[user.id] = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
    }

    # دکمه‌های تأیید
    keyboard = [
        [
            InlineKeyboardButton("✅ بله، منتشر کن", callback_data="confirm"),
            InlineKeyboardButton("❌ نه، لغو کن", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        "آیا این عکس را در کانال منتشر کنم؟",
        reply_markup=reply_markup,
    )
    return CONFIRMING


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پردازش دکمه‌های تأیید/لغو"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = user_data_store.get(user_id)

    if not data:
        await query.edit_message_text("متأسفم، داده‌ای برای انتشار پیدا نشد. لطفاً دوباره عکس را فوروارد کنید.")
        return ConversationHandler.END

    if query.data == "confirm":
        try:
            # فوروارد کردن عکس به کانال
            await context.bot.forward_message(
                chat_id=CHANNEL_ID,
                from_chat_id=data["chat_id"],
                message_id=data["message_id"],
            )
            await query.edit_message_text("✅ عکس با موفقیت در کانال منتشر شد.")
        except Exception as e:
            logger.error(f"خطا در ارسال به کانال: {e}")
            await query.edit_message_text(
                "❌ خطا در انتشار عکس. مطمئن شوید که ربات در کانال ادمین است و شناسه کانال صحیح است."
            )
    else:  # cancel
        await query.edit_message_text("❌ انتشار لغو شد.")

    # پاک کردن داده‌های کاربر
    user_data_store.pop(user_id, None)
    return ConversationHandler.END


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """در صورت دریافت پیام غیرمنتظره"""
    await update.message.reply_text(
        "لطفاً یک عکس فوروارد کنید یا از دکمه‌های تأیید/لغو استفاده کنید.\n"
        "برای خروج، /cancel را بزنید."
    )
    return WAITING_FORWARD


def main() -> None:
    """اجرای اصلی ربات"""
    application = Application.builder().token(TOKEN).build()

    # تنظیم مکالمه
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FORWARD: [
                MessageHandler(filters.PHOTO, handle_forward),
                CommandHandler("cancel", cancel),
            ],
            CONFIRMING: [
                CallbackQueryHandler(confirm_callback, pattern="^(confirm|cancel)$"),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[MessageHandler(filters.ALL, fallback)],
    )

    application.add_handler(conv_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
