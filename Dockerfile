FROM python:3.9-slim

# السطر ده عشان يسطب أداة ffmpeg على السيرفر
RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app
COPY . /app

# السطر ده بيسطب المكتبات
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

# السطر ده عشان يشغل السيرفر 24 ساعة
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]