# -*- coding: utf-8 -*-
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple


# 英文原版曲目名 -> 中文正式曲名映射（用于跨语言查找歌词）
ENG_TITLE_MAP = {
    "a southern city in a late spring day": "春末的南方城市",
    "a vague talk": "暧昧",
    "alan": "阿兰",
    "be with you": "和你在一起",
    "black envelop": "黑色信封",
    "castle in the sky": "天空之城",
    "dingxi": "定西",
    "elephant": "大象",
    "forbidden game": "被禁忌的游戏",
    "has man a future": "这个世界会好吗",
    "it has come": "来了",
    "kafka": "卡夫卡",
    "love": "爱",
    "marriage": "结婚",
    "miss dong": "董卓瑶",
    "moon says my heart": "月亮代表我的心",
    "mr. van gogh": "梵高先生",
    "ms. dong": "董卓瑶",
    "once upon a time": "青春",
    "one night in nowhere": "一个夜晚",
    "red balloon": "红色气球",
    "reflection": "倒影",
    "rehe": "热河",
    "suddenly": "忽然",
    "summer of shanyin road": "山阴路的夏天",
    "the end": "尽头",
    "the memory of zhengzhou": "关于郑州的记忆",
    "they": "他们",
    "weng's 6 pounds": "翁庆年的六英镑",
}


def get_pinyin_tokens(text: str) -> str:
    """
    按需延迟加载 pypinyin 生成全拼和首字母缩写。
    仅供新曲目入库时调用，日常搜歌点播绝对不常驻加载 50MB 拼音词典！
    """
    if not text:
        return ""
    try:
        from pypinyin import lazy_pinyin, Style
        full = "".join(lazy_pinyin(text))
        first = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))
        return f"{full} {first}".lower()
    except ImportError:
        return text.lower()


def get_text_pinyin_parts(text: str) -> Tuple[str, str]:
    """按需延迟加载 pypinyin 返回全拼和首字母（向后兼容接口）"""
    if not text:
        return "", ""
    try:
        from pypinyin import lazy_pinyin, Style
        full = "".join(lazy_pinyin(text)).lower()
        first = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower()
        return full, first
    except ImportError:
        t = text.lower()
        return t, t


def normalize_song_title(title: str) -> str:
    """清洗并标准化歌名（剥离序号、Live标识、中英括号），便于模糊与跨语言查找"""
    if not title:
        return ""
    t = str(title)
    t_lower = t.lower()
    for ek, ev in ENG_TITLE_MAP.items():
        if ek in t_lower:
            return ev
    if re.match(r"^[a-zA-Z\s\d\-_]+[\(（]", t):
        m = re.findall(r"[\(（]([\u4e00-\u9fa5]+)[\)）]", t)
        if m:
            t = m[0]
    t = re.sub(r"^\d{1,3}[\.\s\-_]+", "", t)
    t = re.sub(r"[（\(【\[].*?[）\)】\]]", "", t)
    t = re.sub(r"\d{4}[^\w\s]*版?", "", t)
    t = re.sub(r"(?:Live|现场|不插电|电声|管弦乐|跨年|单曲|交响|翻唱许巍|伴奏版)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[\s\-_，。！？、~—]+", "", t)
    replacements = {
        "曖昧": "暧昧",
        "想起了他": "想起了她",
        "思念的观世音": "思念观世音",
        "1990的春天": "1990年的春天",
        "南方春末的城市": "春末的南方城市",
    }
    for old_s, new_s in replacements.items():
        t = t.replace(old_s, new_s)
    return t.strip()


class MusicDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # 极轻量统计缓存（仅缓存几十条目录汇总，大幅减少点击菜单的重复磁盘查询）
        self._meta_cache: Dict[str, Tuple[float, object]] = {}
        self._cache_ttl = 60.0
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """提供具备自动关闭与超时保护特性的 SQLite 连接管理器"""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _get_cached(self, key: str):
        item = self._meta_cache.get(key)
        if item and (time.monotonic() - item[0]) < self._cache_ttl:
            return item[1]
        return None

    def _set_cached(self, key: str, value: object):
        self._meta_cache[key] = (time.monotonic(), value)

    def _invalidate_cache(self):
        self._meta_cache.clear()

    def _init_db(self):
        """初始化数据库表结构、WAL 防损模式与性能索引"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 开启 WAL 与 NORMAL 同步模式，降低软路由 TF 卡随机写损耗与锁库风险
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")

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
        """录入或更新歌曲信息，并刷新缓存"""
        title = title.strip() if title else (file_name or "未知曲目")
        performer = performer.strip() if performer else "李志"
        album = album.strip() if album else "单曲 / 未归类"
        pinyin = f"{get_pinyin_tokens(title)} {get_pinyin_tokens(album)}"
        year = int(year) if year else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
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
                self._invalidate_cache()
                return False, song_id
            else:
                cursor.execute("""
                    INSERT INTO songs (
                        title, performer, album, year, duration, channel_id, message_id, 
                        file_id, file_unique_id, file_name, lyrics, pinyin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, performer, album, year, duration, str(channel_id), message_id, file_id, file_unique_id, file_name, lyrics, pinyin))
                conn.commit()
                self._invalidate_cache()
                return True, cursor.lastrowid

    def get_all_albums(self) -> List[Dict]:
        """获取所有专辑列表（按编年史排序，带轻量缓存）"""
        cached = self._get_cached("all_albums")
        if cached is not None:
            return cached
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT album, COUNT(*) as track_count, SUM(duration) as total_duration, MAX(year) as year, MIN(message_id) as min_msg_id
                FROM songs
                GROUP BY album
                ORDER BY year ASC, album ASC
            """)
            res = [dict(row) for row in cursor.fetchall()]
            self._set_cached("all_albums", res)
            return res

    def get_songs_by_album(self, album: str) -> List[Dict]:
        """根据专辑名称获取其中的曲目列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs WHERE album = ? ORDER BY id ASC", (album,))
            return [dict(row) for row in cursor.fetchall()]

    def _find_lyrics_in_db(self, clean_name: str, conn: sqlite3.Connection) -> Optional[str]:
        """利用数据库已有歌词片段进行精确或清洗后匹配"""
        if not clean_name or len(clean_name) < 2:
            return None
        cursor = conn.cursor()
        cursor.execute(
            "SELECT lyrics FROM songs WHERE lyrics IS NOT NULL AND length(trim(lyrics)) > 10 AND (title = ? OR title LIKE ?) ORDER BY id ASC LIMIT 1",
            (clean_name, f"%{clean_name}%")
        )
        row = cursor.fetchone()
        return row["lyrics"] if row else None

    def get_song_lyrics(self, song: Dict) -> Optional[str]:
        """
        统一单一数据源歌词查询引擎：
        1. 优先直接返回该首歌曲自身的 songs.lyrics；
        2. 若缺失，自动清洗别名/英文译名后从同曲库已有版本检索；
        3. 若属于联唱曲目（例如 "前奏+黑色信封+定西"），自动拆段并从数据库拼接各段原版歌词！
        """
        if not song:
            return None
        direct_lrc = (song.get("lyrics") or "").strip()
        if direct_lrc:
            return direct_lrc

        raw_title = song.get("title") or ""
        if not raw_title:
            return None

        with self._get_connection() as conn:
            # 尝试规范化名称（涵盖英文直译映射）
            clean_t = normalize_song_title(raw_title)
            matched = self._find_lyrics_in_db(clean_t, conn)
            if matched:
                return matched

            # 尝试联唱曲目拆分匹配（如 "A+B+C" 或 "他们 广场"）
            parts = re.split(r"[\+&/、\s]+", raw_title)
            if len(parts) > 1:
                sections = []
                for part in parts:
                    part_clean = normalize_song_title(part)
                    if not part_clean or len(part_clean) < 2:
                        continue
                    part_lrc = self._find_lyrics_in_db(part_clean, conn)
                    if part_lrc:
                        sections.append(f"🎵 **《{part_clean}》**\n{part_lrc}")
                if sections:
                    return "\n\n━━━━━━━━━━━━━━━━━━━━━\n\n".join(sections)

        return None

    def search_songs(self, query: str, limit: int = 15) -> List[Dict]:
        """
        零 pypinyin 运行时消耗的极速加权搜歌（直接基于预存拼音索引与数据库歌词全文）
        """
        q = query.strip().lower()
        if not q:
            return []

        pattern = f"%{q}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM songs
                WHERE LOWER(title) LIKE ? 
                   OR LOWER(album) LIKE ? 
                   OR LOWER(pinyin) LIKE ?
                   OR LOWER(lyrics) LIKE ?
                LIMIT 80
            """, (pattern, pattern, pattern, pattern))
            rows = [dict(row) for row in cursor.fetchall()]

        if not rows:
            return []

        # 提取歌词逆向命中摘要片段
        for s in rows:
            s["lyric_snippet"] = ""
            lrc = s.get("lyrics")
            if lrc and q in lrc.lower():
                for line in lrc.splitlines():
                    if q in line.lower():
                        snippet = line.strip()
                        if len(snippet) > 32:
                            snippet = snippet[:30] + "..."
                        s["lyric_snippet"] = snippet
                        break

        def calculate_score(s: Dict) -> int:
            title = (s.get("title") or "").lower()
            album = (s.get("album") or "").lower()
            pinyin_raw = (s.get("pinyin") or "").lower()
            tokens = pinyin_raw.split()

            # 从数据库预存的 pinyin 串中剥离歌名拼音区间与专辑拼音区间（末尾两段通常为专辑全拼/首字母）
            if len(tokens) >= 4:
                album_tokens = tokens[-2:]
                title_tokens = tokens[:-2]
            else:
                album_tokens = []
                title_tokens = tokens

            title_pinyin_joined = "".join(title_tokens)
            album_pinyin_joined = "".join(album_tokens)

            # 1. 歌名完全匹配
            if title == q:
                return 1000
            # 2. 歌名首字母 / 独立拼音Token完全匹配（如 fgxs 命中 梵高先生）
            if q in title_tokens:
                # 最后一个通常是首字母简拼，赋予最高分
                if title_tokens and q == title_tokens[-1]:
                    return 900
                return 750
            # 3. 歌名拼音连写/包含命中
            if q in title_pinyin_joined:
                return 800 if len(q) <= 6 else 700
            # 4. 歌名文本包含
            if q in title:
                return 600
            # 5. 歌词逆向命中
            if s.get("lyric_snippet"):
                return 450
            # 6. 专辑完全匹配
            if album == q:
                return 400
            # 7. 专辑拼音完全/包含命中
            if q in album_tokens:
                return 350
            if q in album_pinyin_joined:
                return 300
            # 8. 专辑文本包含
            if q in album:
                return 200
            return 100

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
        """获取当前曲库总计统计数据（带缓存）"""
        cached = self._get_cached("song_stats")
        if cached is not None:
            return cached
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM songs")
            song_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT album) FROM songs")
            album_count = cursor.fetchone()[0]
            res = {"songs": song_count, "albums": album_count}
            self._set_cached("song_stats", res)
            return res

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
        """高质量随机获取一首单曲（优先时长 > 80 秒）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs WHERE duration > 80 ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT * FROM songs ORDER BY RANDOM() LIMIT 1")
                row = cursor.fetchone()
            return dict(row) if row else None

    def get_random_songs(self, limit: int = 10) -> List[Dict]:
        """随机获取指定数量的单曲"""
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
        """获取视频库总数与分类统计（带缓存）"""
        cached = self._get_cached("video_stats")
        if cached is not None:
            return cached
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM videos")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT category) FROM videos")
            cat_cnt = cursor.fetchone()[0]
            res = {"videos": total, "categories": cat_cnt}
            self._set_cached("video_stats", res)
            return res

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
        """随机获取一部视频"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("SELECT * FROM videos WHERE category = ? ORDER BY RANDOM() LIMIT 1", (category,))
            else:
                cursor.execute("SELECT * FROM videos ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_video_categories(self) -> List[Tuple[str, int]]:
        """获取所有视频分类及其数量（带缓存）"""
        cached = self._get_cached("video_cats")
        if cached is not None:
            return cached
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
            res = [(r[0], r[1]) for r in cursor.fetchall()]
            self._set_cached("video_cats", res)
            return res

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
        idx = next((i for i, t in enumerate(tracks) if t["id"] == song_id), -1)
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
        core_title = next((kw for kw in core_keywords if kw in raw_title), "")
        if not core_title:
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
            return core_title, [dict(r) for r in cursor.fetchall()]

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if city_name in city_sql_map:
                cursor.execute(f"SELECT * FROM songs WHERE {city_sql_map[city_name]} ORDER BY year ASC, id ASC")
            else:
                pat = f"%{city_name}%"
                cursor.execute("SELECT * FROM songs WHERE title LIKE ? OR album LIKE ? ORDER BY year ASC, id ASC", (pat, pat))
            return [dict(r) for r in cursor.fetchall()]

    def get_related_video_for_song(self, song_title: str) -> Optional[Dict]:
        """寻找与当前单曲密切对应的高清现场视频"""
        keywords = {
            "洗心革面": "洗心革面", "吉隆坡": "吉隆坡", "东京": "东京",
            "工体东路": "工体东路", "星光现场": "将进酒", "将进酒": "将进酒",
            "最后一枪": "最后一枪", "和你在一起": "和你在一起", "梵高先生": "梵高先生",
            "看见": "看见", "动静": "降噪", "电声与管弦乐": "电声与管弦乐",
            "爵士乐": "爵士乐", "108个关键词": "108个关键词", "去没有去过的地方": "去没有去过的地方",
            "波士顿": "波士顿", "杀鸡取卵": "杀鸡取卵", "一身酒气": "一身酒气",
            "简单生活节": "简单生活节"
        }
        target_kw = next((v for k, v in keywords.items() if k in song_title), None)
        if not target_kw:
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE LOWER(title) LIKE ? ORDER BY year DESC LIMIT 1", (f"%{target_kw.lower()}%",))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== 会话状态持久化 (Single-Message Hub) ====================
    def get_user_session(self, user_id: int) -> Optional[Dict]:
        """获取指定用户的常驻控制台活跃会话"""
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
        """解析返回李志硬核乐迷级音频母带规格徽章"""
        fn = (song.get("file_name") or "").lower()
        album = song.get("album", "")

        if fn.endswith(".wav"):
            if "Best Selection" in album or "Tokyo" in album or "叁缺壹" in album:
                return "[WAV 24bit Hi-Res 母带]"
            return "[WAV 无损原盘]"

        if fn.endswith(".flac"):
            if "Best Selection" in album:
                return "[FLAC 24bit/96kHz 海外重制]"
            if "电声与管弦乐" in album or album in ("李志 1701", "8", "在每一条伤心的应天大街上"):
                return "[FLAC 24bit 高解析母带]"
            if album in ("被禁忌的游戏", "梵高先生", "这个世界会好吗", "我爱南京", "你好，郑州", "F"):
                return "[FLAC 16bit CD首版无损]"
            return "[FLAC 16bit 无损现场]"

        if fn.endswith(".m4a"):
            return "[Apple AAC 256K 高保真]"

        if fn.endswith(".mp3"):
            if "吉隆坡" in album or "2025" in album or "洗心革面" in album:
                return "[320Kbps HQ 现场原音]"
            if "民间现场录音" in str(album) or "义乌" in album or "一身酒气" in album:
                return "[320Kbps 乐迷珍贵现场]"
            return "[320Kbps HQ 极高品质]"

        return "[高品质音频]"
