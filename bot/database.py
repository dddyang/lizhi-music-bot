import sqlite3
import os
from contextlib import contextmanager
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

    def get_text_pinyin_parts(text: str) -> Tuple[str, str]:
        """返回文本的全拼和首字母"""
        if not text:
            return "", ""
        full = "".join(lazy_pinyin(text)).lower()
        first = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower()
        return full, first
except ImportError:
    def get_pinyin_tokens(text: str) -> str:
        return text.lower() if text else ""

    def get_text_pinyin_parts(text: str) -> Tuple[str, str]:
        return (text.lower(), text.lower()) if text else ("", "")

class MusicDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """提供具备自动关闭特性的 SQLite 连接上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    category_folder TEXT,
                    year INTEGER DEFAULT 0,
                    duration INTEGER DEFAULT 0,
                    duration_str TEXT,
                    size_mb REAL DEFAULT 0.0,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    link TEXT NOT NULL,
                    pinyin TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, message_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_cat ON videos(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_title ON videos(title)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_year ON videos(year)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_pinyin ON videos(pinyin)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL DEFAULT 0,
                    message_id INTEGER NOT NULL DEFAULT 0,
                    last_category TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
        """按标题、专辑名、拼音或歌词智能加权搜索"""
        q = query.strip().lower()
        if not q:
            return []

        # 1. 尝试从 LYRICS_DATABASE 中逆向检索歌词命中的歌曲名
        lyric_hits = {}  # title -> snippet
        try:
            from lyrics_bank import LYRICS_DATABASE
            for l_title, l_text in LYRICS_DATABASE.items():
                if q in l_text.lower():
                    for line in l_text.splitlines():
                        if q in line.lower():
                            snippet = line.strip()
                            if len(snippet) > 32:
                                snippet = snippet[:30] + "..."
                            lyric_hits[l_title] = snippet
                            break
        except Exception:
            pass

        pattern = f"%{q}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 宽表多维度召回候选曲目
            sql = """
                SELECT * FROM songs
                WHERE LOWER(title) LIKE ? 
                   OR LOWER(album) LIKE ? 
                   OR pinyin LIKE ?
                   OR LOWER(lyrics) LIKE ?
            """
            params = [pattern, pattern, pattern, pattern]
            if lyric_hits:
                placeholders = ",".join("?" for _ in lyric_hits)
                sql += f" OR title IN ({placeholders})"
                params.extend(list(lyric_hits.keys()))

            sql += " LIMIT 80"
            cursor.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]

        if not rows:
            return []

        # 为命中的歌词提取或注入 snippet
        for s in rows:
            title = s["title"]
            s["lyric_snippet"] = ""
            if title in lyric_hits:
                s["lyric_snippet"] = lyric_hits[title]
            elif s.get("lyrics") and q in s["lyrics"].lower():
                for line in s["lyrics"].splitlines():
                    if q in line.lower():
                        snippet = line.strip()
                        if len(snippet) > 32:
                            snippet = snippet[:30] + "..."
                        s["lyric_snippet"] = snippet
                        break

        # 智能打分：歌名完全匹配 > 拼音完全匹配 > 拼音包含 > 歌名文本包含 > 歌词命中 > 专辑包含
        def calculate_score(s: Dict) -> int:
            title = s["title"].lower()
            album = s["album"].lower()
            t_full, t_first = get_text_pinyin_parts(title)
            a_full, a_first = get_text_pinyin_parts(album)

            # 1. 歌名完全匹配 (如搜 "梵高先生")
            if title == q:
                return 1000
            # 2. 歌名首字母完全匹配 (如搜 "fgxs" 命中 "梵高先生")
            if t_first == q:
                return 900
            # 3. 歌名首字母包含 (如搜 "zz" 命中 "关于郑州的记忆")
            if q in t_first:
                return 800
            # 4. 歌名全拼完全匹配
            if t_full == q:
                return 750
            # 5. 歌名全拼包含
            if q in t_full:
                return 700
            # 6. 歌名文本包含 (如搜 "郑州")
            if q in title:
                return 600
            # 7. 歌词包含命中（逆向搜歌赋予 450 分的高优先级，高过单纯的专辑名命中）
            if s.get("lyric_snippet"):
                return 450
            # 8. 专辑完全匹配 (如搜 "1701")
            if album == q:
                return 400
            # 9. 专辑首字母完全匹配
            if a_first == q:
                return 350
            # 10. 专辑首字母包含
            if q in a_first:
                return 300
            # 11. 专辑文本包含
            if q in album:
                return 200
            return 100

        # 按打分降序排列，相同得分按 ID 自然排序
        rows.sort(key=lambda s: (calculate_score(s), -s["id"]), reverse=True)
        return rows[:limit]

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
        """高质量随机获取一首单曲（优先推荐时长 > 80 秒的完整作品，避免极短过渡曲）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM songs 
                WHERE duration > 80 
                ORDER BY RANDOM() 
                LIMIT 1
            """)
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT * FROM songs ORDER BY RANDOM() LIMIT 1")
                row = cursor.fetchone()
            return dict(row) if row else None

    def get_random_songs(self, limit: int = 10) -> List[Dict]:
        """全曲库随机获取指定数量的单曲，用于行内搜索默认推荐等场景"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs ORDER BY RANDOM() LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_songs(self) -> List[Dict]:
        """获取曲库中的所有曲目"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    # ==================== 影音视频库相关接口 ====================
    def get_video_stats(self) -> Dict[str, int]:
        """获取视频库总数与分类统计"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM videos")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT category) FROM videos")
            cat_cnt = cursor.fetchone()[0]
            return {"videos": total, "categories": cat_cnt}

    def search_videos(self, query: str, limit: int = 10) -> List[Dict]:
        """模糊搜索视频，支持中文、拼音首字母和全拼"""
        q = query.strip().lower()
        if not q:
            return []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM videos 
                WHERE LOWER(title) LIKE ? 
                   OR LOWER(category) LIKE ?
                   OR LOWER(pinyin) LIKE ?
                ORDER BY year DESC, id DESC
                LIMIT ?
            """, (f"%{q}%", f"%{q}%", f"%{q}%", limit))
            return [dict(r) for r in cursor.fetchall()]

    def get_videos_by_category(self, category: str, limit: int = 20, offset: int = 0) -> Tuple[List[Dict], int]:
        """按分类获取视频列表，支持分页"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM videos WHERE category = ?", (category,))
            total = cursor.fetchone()[0]
            cursor.execute("""
                SELECT * FROM videos 
                WHERE category = ?
                ORDER BY year ASC, title ASC, id ASC
                LIMIT ? OFFSET ?
            """, (category, limit, offset))
            return [dict(r) for r in cursor.fetchall()], total

    def get_random_video(self, category: Optional[str] = None) -> Optional[Dict]:
        """全库或指定分类随机获取一部视频"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("SELECT * FROM videos WHERE category = ? ORDER BY RANDOM() LIMIT 1", (category,))
            else:
                cursor.execute("SELECT * FROM videos ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_video_categories(self) -> List[Tuple[str, int]]:
        """获取所有视频分类及其数量"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, COUNT(*) as cnt 
                FROM videos 
                GROUP BY category 
                ORDER BY 
                    CASE category 
                        WHEN '历年跨年与演唱会现场' THEN 1 
                        WHEN '叁叁肆巡演官方纪录片' THEN 2 
                        WHEN '逼哥夜话与深度对谈' THEN 3 
                        WHEN '精选专访与珍贵纪录片' THEN 4 
                        WHEN '经典现场单曲精选' THEN 5 
                        ELSE 6 END ASC
            """)
            return [(r[0], r[1]) for r in cursor.fetchall()]

    def get_video_by_id(self, video_id: int) -> Optional[Dict]:
        """按 ID 精确获取视频"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== 专业点播增强接口 ====================
    def get_album_track_nav(self, album: str, song_id: int) -> Tuple[Optional[Dict], Optional[Dict], int, int]:
        """获取专辑内曲目的当前序号、总曲数、上一首和下一首信息"""
        tracks = self.get_songs_by_album(album)
        total = len(tracks)
        idx = -1
        for i, t in enumerate(tracks):
            if t["id"] == song_id:
                idx = i
                break
        if idx == -1:
            return None, None, 0, total
        prev_song = tracks[idx - 1] if idx > 0 else None
        next_song = tracks[idx + 1] if idx < total - 1 else None
        return prev_song, next_song, idx + 1, total

    def get_other_versions(self, song_id: int) -> Tuple[str, List[Dict]]:
        """获取同名歌曲在其他专辑中的现场与录音室版本"""
        song = self.get_song_by_id(song_id)
        if not song:
            return "", []

        # 核心歌名提取
        raw_title = song["title"]
        core_keywords = [
            "被禁忌的游戏", "梵高先生", "董卓瑶", "黑色信封", "卡夫卡", "阿兰",
            "这个世界会好吗", "海的女儿", "妈妈", "翁庆年的六角飞碟", "我们不能失去信仰",
            "我爱南京", "天空之城", "倒影", "关于郑州的记忆", "再见", "家乡", "米店",
            "你好，郑州", "定西", "墙上的向日葵", "铅笔", "尽头",
            "山阴路的夏天", "下雨", "寻找", "爱", "莫须有", "热河", "杭州",
            "1701", "大象", "回答", "门", "方式", "看见", "动静",
            "在每一条伤心的应天大街上", "应天大街", "一胀一落",
            "和你在一起", "工体东路没有人", "二零零九年十月十六日事件", "我们也爱南京",
            "洗心革面", "不多", "兰州", "金城兰州", "最后一枪", "苍井空", "婚誓"
        ]
        core_title = ""
        for kw in core_keywords:
            if kw in raw_title:
                core_title = kw
                break
        if not core_title:
            import re
            t = re.sub(r'^\d+[\.、\s]*', '', raw_title)
            t = re.sub(r'[\(（\[【][^\)）\]】]+[\)）\]】]', '', t)
            t = re.sub(r'\s*(Live|unplugged|节选|现场|版).*$', '', t, flags=re.I)
            core_title = t.strip() or raw_title.strip()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM songs 
                WHERE (LOWER(title) LIKE ? OR LOWER(title) = ?) AND id != ?
                ORDER BY year ASC, album ASC, id ASC
            """, (f"%{core_title.lower()}%", core_title.lower(), song_id))
            rows = [dict(r) for r in cursor.fetchall()]
            return core_title, rows

    def get_songs_by_city(self, city_name: str) -> List[Dict]:
        """按城市地标检索李志经典单曲"""
        city_sql_map = {
            "南京": "title LIKE '%南京%' OR album LIKE '%南京%' OR title LIKE '%天空之城%' OR title LIKE '%山阴路%' OR title LIKE '%热河%' OR title LIKE '%应天大街%'",
            "郑州": "title LIKE '%郑州%' OR album LIKE '%郑州%'",
            "兰州": "title LIKE '%兰州%' OR album LIKE '%兰州%'",
            "成都": "title LIKE '%成都%' OR title LIKE '%江城子%'",
            "杭州": "title LIKE '%杭州%' OR album LIKE '%杭州%'",
            "北京": "title LIKE '%北京%' OR album LIKE '%工体%'",
            "定西": "title LIKE '%定西%'",
        }
        condition = city_sql_map.get(city_name, f"title LIKE '%{city_name}%' OR album LIKE '%{city_name}%'")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM songs WHERE {condition} ORDER BY year ASC, id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def get_related_video_for_song(self, song_title: str) -> Optional[Dict]:
        """寻找与当前单曲密切对应的高清现场视频（如全场演唱会或单曲）"""
        keywords = {
            "洗心革面": "洗心革面",
            "吉隆坡": "吉隆坡",
            "东京": "东京",
            "工体东路": "工体东路",
            "星光现场": "将进酒",
            "将进酒": "将进酒",
            "最后一枪": "最后一枪",
            "和你在一起": "和你在一起",
            "梵高先生": "梵高先生",
            "看见": "看见",
            "动静": "降噪",
            "电声与管弦乐": "电声与管弦乐",
            "爵士乐": "爵士乐",
            "108个关键词": "108个关键词",
            "去没有去过的地方": "去没有去过的地方",
            "波士顿": "波士顿",
            "杀鸡取卵": "杀鸡取卵",
            "一身酒气": "一身酒气",
            "简单生活节": "简单生活节"
        }
        target_kw = None
        for k, v in keywords.items():
            if k in song_title:
                target_kw = v
                break
        if not target_kw:
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE LOWER(title) LIKE ? ORDER BY year DESC LIMIT 1", (f"%{target_kw.lower()}%",))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== 会话状态持久化 (Single-Message Hub) ====================
    def get_user_session(self, user_id: int) -> Optional[Dict]:
        """获取指定用户的常驻控制台活跃会话（保证服务重启后依然精准衔接）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_sessions WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_user_session(self, user_id: int, chat_id: int, message_id: int, last_category: Optional[str] = None):
        """持久化记录或更新当前常驻控制台消息 ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if last_category is not None:
                cursor.execute("""
                    INSERT INTO user_sessions (user_id, chat_id, message_id, last_category, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        chat_id = excluded.chat_id,
                        message_id = excluded.message_id,
                        last_category = excluded.last_category,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, chat_id, message_id, last_category))
            else:
                cursor.execute("""
                    INSERT INTO user_sessions (user_id, chat_id, message_id, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        chat_id = excluded.chat_id,
                        message_id = excluded.message_id,
                        updated_at = CURRENT_TIMESTAMP
                """, (user_id, chat_id, message_id))
            conn.commit()

    def update_user_last_cat(self, user_id: int, last_category: str):
        """持久化记忆用户最后浏览的专辑分类"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_sessions (user_id, chat_id, message_id, last_category, updated_at)
                VALUES (?, 0, 0, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    last_category = excluded.last_category,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, last_category))
            conn.commit()

    # ==================== 音质与母带规格智能判定 ====================
    @staticmethod
    def get_song_quality_tag(song: Dict) -> str:
        """
        根据音频格式扩展名与专辑发行特性，解析返回李志硬核乐迷级音频母带规格徽章
        """
        fn = (song.get("file_name") or "").lower()
        album = song.get("album", "")

        # 1. WAV 原盘与录音室分轨母带
        if fn.endswith(".wav"):
            if "Best Selection" in album or "Tokyo" in album or "叁缺壹" in album:
                return "[WAV 24bit Hi-Res 母带]"
            return "[WAV 无损原盘]"

        # 2. FLAC 无损
        if fn.endswith(".flac"):
            if "Best Selection" in album:
                return "[FLAC 24bit/96kHz 海外重制]"
            elif "电声与管弦乐" in album or album in ("李志 1701", "8", "在每一条伤心的应天大街上"):
                return "[FLAC 24bit 高解析母带]"
            elif album in ("被禁忌的游戏", "梵高先生", "这个世界会好吗", "我爱南京", "你好，郑州", "F"):
                return "[FLAC 16bit CD首版无损]"
            else:
                return "[FLAC 16bit 无损现场]"

        # 3. M4A / AAC 高保真
        if fn.endswith(".m4a"):
            return "[Apple AAC 256K 高保真]"

        # 4. MP3 极高码率
        if fn.endswith(".mp3"):
            if "吉隆坡" in album or "2025" in album or "洗心革面" in album:
                return "[320Kbps HQ 现场原音]"
            elif "民间现场录音" in str(album) or "义乌" in album or "一身酒气" in album:
                return "[320Kbps 乐迷珍贵现场]"
            else:
                return "[320Kbps HQ 极高品质]"

        return "[高品质音频]"



