#!/bin/sh
# NanoPi R2S 极速启动脚本

echo "=== 正在启动李志音乐机器人 ==="

# 检查 Python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "未检测到 Python3，正在通过 opkg / apt 安装..."
    if command -v opkg >/dev/null 2>&1; then
        opkg update && opkg install python3 python3-pip python3-sqlite3
    elif command -v apt >/dev/null 2>&1; then
        apt update && apt install -y python3 python3-pip python3-venv
    fi
fi

# 安装 Python 依赖
pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 停止旧进程
kill $(pgrep -f "python3 bot.py") 2>/dev/null

# 后台静默启动
nohup python3 bot.py > bot.log 2>&1 &

echo "✅ 机器人已成功在后台常驻运行！"
echo "📄 查看实时运行日志命令: tail -f bot.log"
