import os

# توکن ربات (از Railway یا سیستم می‌خونه)
BOT_TOKEN = os.environ["BOT_TOKEN"]

# کانال مقصد برای انتشار پست‌ها
CHANNEL = "@spark_news_tel"

# لیست آیدی عددی کاربران مجاز
ALLOWED_USERS = [8293164271]

# مدت زمان (ثانیه) عدم فعالیت برای پاک‌سازی خودکار وضعیت‌ها
STATE_TTL = 600  # 10 دقیقه
