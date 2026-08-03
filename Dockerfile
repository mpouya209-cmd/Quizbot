FROM python:3.13-slim

# نصب ابزارهای سیستمی مورد نیاز برای OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# تنظیم پوشه کاری
WORKDIR /app

# کپی کردن فایل‌های پروژه
COPY . .

# نصب کتابخانه‌های پایتون
RUN pip install --no-cache-dir -r requirements.txt

# اجرای ربات
CMD bash start.sh
