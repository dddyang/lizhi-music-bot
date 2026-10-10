import sqlite3
import os
from typing import List, Dict, Optional, Tuple

try:
    from pypinyin import lazy_pinyin, Style
    def get_pinyin_tokens(text: str) -> str:
        """生成全拼和首字母缩写，便于拼音搜索"""
        if not text:
            return ""
        full = "".join(lazy_pinyin(text))
        first = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))
        return f"{full} {first}".lower()
except ImportError:
    def get_pinyin_tokens(text: str) -> str:
        return text.lower() if text else ""

class MusicDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表结构与索引"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    performer TEXT,
                    album TEXT DEFAULT '未分类专辑',
                    year INTEGER DEFAULT 0,
                    duration INTEGER DEFAULT 0,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    file_unique_id TEXT,
                    file_name TEXT,
                    lyrics TEXT,
                    pinyin TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, message_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_album ON songs(album)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_title ON songs(title)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_year ON songs(year)")
            conn.commit()

    def add_or_update_song(
        self,
        title: str,
        performer: Optional[str],
        album: Optional[str],
        duration: int,
        channel_id: str,
        message_id: int,
        file_id: str,
        file_unique_id: str,
        file_name: Optional[str] = None,
        year: Optional[int] = None,
        lyrics: Optional[str] = None
    ) -> Tuple[bool, int]:
        """
        录入或更新歌曲信息
        返回: (is_new, song_id)
        """
        title = title.strip() if title else (file_name or "未知曲目")
        performer = performer.strip() if performer else "李志"
        album = album.strip() if album else "单曲 / 未归类"
        pinyin = f"{get_pinyin_tokens(title)} {get_pinyin_tokens(album)}"
        year = int(year) if year else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 检查是否已存在（按 channel_id + message_id 唯一确认频道消息）
            cursor.execute("SELECT id FROM songs WHERE channel_id = ? AND message_id = ?", (str(channel_id), message_id))
            existing = cursor.fetchone()

            if existing:
                song_id = existing["id"]
                cursor.execute("""
                    UPDATE songs 
                    SET title = ?, performer = ?, album = ?, year = ?, duration = ?, 
                        channel_id = ?, message_id = ?, file_id = ?, file_name = ?, pinyin = ?,
                        lyrics = COALESCE(?, lyrics)
                    WHERE id = ?
                """, (title, performer, album, year, duration, str(channel_id), message_id, file_id, file_name, pinyin, lyrics, song_id))
                conn.commit()
                return False, song_id
            else:
                cursor.execute("""
                    INSERT INTO songs (
                        title, performer, album, year, duration, channel_id, message_id, 
                        file_id, file_unique_id, file_name, lyrics, pinyin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, performer, album, year, duration, str(channel_id), message_id, file_id, file_unique_id, file_name, lyrics, pinyin))
                conn.commit()
                return True, cursor.lastrowid


    def get_all_albums(self) -> List[Dict]:
        """获取所有专辑列表及每张专辑的歌曲数量、年份与总时长（按年份编年史排序）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT album, COUNT(*) as track_count, SUM(duration) as total_duration, MAX(year) as year, MIN(message_id) as min_msg_id
                FROM songs
                GROUP BY album
                ORDER BY year ASC, album ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_songs_by_album(self, album: str) -> List[Dict]:
        """根据专辑名称获取其中的曲目列表（按文件名与消息ID自然排序）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM songs 
                WHERE album = ?
                ORDER BY id ASC
            """, (album,))
            return [dict(row) for row in cursor.fetchall()]

    def search_songs(self, query: str, limit: int = 15) -> List[Dict]:
        """按标题、专辑名或拼音模糊搜索"""
        query = query.strip().lower()
        if not query:
            return []

        pattern = f"%{query}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM songs
                WHERE LOWER(title) LIKE ? 
                   OR LOWER(album) LIKE ? 
                   OR pinyin LIKE ?
                ORDER BY 
                    CASE 
                        WHEN LOWER(title) = ? THEN 1
                        WHEN LOWER(title) LIKE ? THEN 2
                        ELSE 3
                    END,
                    id ASC
                LIMIT ?
            """, (pattern, pattern, pattern, query, f"{query}%", limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_song_by_id(self, song_id: int) -> Optional[Dict]:
        """根据 ID 获取单曲信息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_stats(self) -> Dict[str, int]:
        """获取当前曲库总计统计数据"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM songs")
            song_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT album) FROM songs")
            album_count = cursor.fetchone()[0]
            return {"songs": song_count, "albums": album_count}

    def has_song(self, title: str, album: str) -> bool:
        """检查某首歌曲是否已经上传并入库"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM songs WHERE LOWER(title) = ? AND LOWER(album) = ?",
                (title.strip().lower(), album.strip().lower())
            )
            return cursor.fetchone() is not None

    def get_random_song(self) -> Optional[Dict]:
        """全曲库随机获取一首单曲"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_songs(self) -> List[Dict]:
        """获取曲库中的所有曲目"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

