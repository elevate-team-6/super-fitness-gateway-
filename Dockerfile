# استخدام نسخة بايثون خفيفة وسريعة
FROM python:3.11-slim

# تحديد مسار العمل جوه السيرفر
WORKDIR /app

# نسخ ملف المكتبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# فتح البورت رقم 8080 (ده البورت المناسب لـ Back4App)
EXPOSE 8080

# أمر تشغيل السيرفر - المسار هنا صحيح بناءً على صورتك
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]