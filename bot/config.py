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

_db_env = os.getenv("DB_PATH", "music.db")
if (BASE_DIR / _db_env).exists() and (BASE_DIR / _db_env).stat().st_size > 100000:
    DB_PATH = str(BASE_DIR / _db_env)
elif (BASE_DIR.parent / _db_env).exists():
    DB_PATH = str(BASE_DIR.parent / _db_env)
else:
    DB_PATH = str(BASE_DIR / _db_env)

# 本地曲库与转码工具路径（用于 auto_uploader.py）
MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", r"Z:\音乐\李志"))
FFMPEG_PATH = Path(os.getenv("FFMPEG_PATH", r"D:\AI\剪映\JianyingPro\11.5.3.14501\ffmpeg.exe"))
