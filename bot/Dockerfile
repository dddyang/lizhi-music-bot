# 使用官方轻量 Python 镜像 (完美支持 ARM64 / R2S)
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝代码与数据库
COPY . .

# 启动机器人
CMD ["python", "bot.py"]
