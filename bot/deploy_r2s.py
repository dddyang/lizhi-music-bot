import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SCRATCH = Path(os.getenv("TEMP", ".")) / ".r2s_deploy"
SCRATCH.mkdir(parents=True, exist_ok=True)

# 安全读取密码：绝不在代码中硬编码任何默认密码！
# 优先级：1. 环境变量 R2S_PASSWORD -> 2. 本地 .env 文件 -> 3. 交互式命令行输入
r2s_pwd = os.getenv("R2S_PASSWORD")
if not r2s_pwd:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("R2S_PASSWORD="):
                    r2s_pwd = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    break

if not r2s_pwd:
    import getpass
    r2s_pwd = getpass.getpass("请输入 R2S 路由器的 SSH 密码: ")

if not r2s_pwd:
    print("❌ 未提供 R2S 密码，部署终止。")
    sys.exit(1)

askpass = SCRATCH / "askpass.cmd"
with open(askpass, "w", encoding="ascii") as f:
    f.write(f"@echo off\necho {r2s_pwd}\n")

env = os.environ.copy()
env["SSH_ASKPASS"] = str(askpass)
env["SSH_ASKPASS_REQUIRE"] = "force"
env["DISPLAY"] = "dummy:0"

try:
    print(">>> 正在上传 bot.py, assets 静态资源, lyrics_bank.py 与 music.db 到 R2S (192.168.100.1)...")
    res = subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-r",
         "bot/bot.py", "bot/database.py", "bot/lyrics_bank.py", "bot/mood_quotes.py", "bot/assets", "music.db", "root@192.168.100.1:/root/tg-music-bot/"],
        cwd=r"D:\AI\电报机器人",
        env=env,
        capture_output=True,
        text=True
    )
    if res.returncode != 0:
        print("SCP Failed:", res.stderr)
        sys.exit(1)
    else:
        print("✅ 上传成功！")

    print(">>> 正在远程重启 tg-music-bot 服务...")
    res2 = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "root@192.168.100.1",
         "/etc/init.d/tg-music-bot restart; sleep 2; /etc/init.d/tg-music-bot status; ps | grep bot.py"],
        env=env,
        capture_output=True,
        text=True
    )
    print("SSH Output:")
    print(res2.stdout)
    if res2.stderr:
        print("SSH Stderr:", res2.stderr)

    print("🎉 部署并重启顺利完成！")
finally:
    if askpass.exists():
        askpass.unlink()
