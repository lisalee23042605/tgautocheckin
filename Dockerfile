FROM python:3.12-slim

WORKDIR /app

# 字体用于生成“截图”图片
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY README.md .

# session 可选存这里（如果不用 SESSION_STRING）
VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
