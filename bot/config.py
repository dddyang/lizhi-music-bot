import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 配置文件（优先当前目录，若无则向上查找父级目录）
BASE_DIR = Path(__file__).resolve().parent
env_file = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parent / ".env"
load_dotenv(env_file)


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# 频道 ID 可以是负整数（如 -100xxxxxxxxxx）或字符串形式的频道用户名（如 @lizhi_music）
_raw_channel_id = os.getenv("CHANNEL_ID", "").strip()
if _raw_channel_id.startswith("-100") or _raw_channel_id.isdigit() or (_raw_channel_id.startswith("-") and _raw_channel_id[1:].isdigit()):
    CHANNEL_ID = int(_raw_channel_id)
else:
    CHANNEL_ID = _raw_channel_id

DB_PATH = str(BASE_DIR / os.getenv("DB_PATH", "music.db"))
