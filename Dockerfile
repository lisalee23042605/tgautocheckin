# 使用官方 Python 镜像作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    chromium \
    chromium-driver \
    libnss3 \
    libgdk-pixbuf2.0-0 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libxss1 \
    libgdk-pixbuf2.0-0 \
    libasound2 \
    fonts-liberation \
    libappindicator3-1 \
    libgbm1 \
    libu2f-udev \
    && apt-get clean

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目文件到容器中
COPY . /app

# 设置环境变量
ENV DISPLAY=:99

# 运行 start.sh 脚本，启动 Python 脚本
ENTRYPOINT ["sh", "start.sh"]
