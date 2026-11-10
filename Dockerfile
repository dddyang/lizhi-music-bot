# 专为李志音乐流媒体服务构建的高性能轻量容器
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PORT=8880

# 安装最小化 MTProto 与异步 HTTP 核心库
RUN pip install --no-cache-dir telethon>=1.34.0 aiohttp>=3.9.0

# 拷贝流媒体服务代码与 529 首全曲库元数据
COPY bot/stream_server.py .
COPY music.db .

# 暴露端口 (默认 8880 端口，可通过环境变量 PORT 动态调整)
EXPOSE 8880

# 启动流媒体中继
CMD ["python", "stream_server.py"]
