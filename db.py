import sqlite3
from datetime import datetime, timezone
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_key TEXT NOT NULL,
                filename TEXT NOT NULL,
                video_id TEXT,
                title TEXT,
                privacy_status TEXT,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_key TEXT NOT NULL,
                region TEXT NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_title TEXT,
                views INTEGER,
                views_per_hour REAL,
                published_at TEXT,
                captured_at TEXT NOT NULL
            )
            """
        )


def log_upload(channel_key, filename, video_id, title, privacy_status, status, message=""):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO upload_logs (channel_key, filename, video_id, title, privacy_status, status, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel_key,
                filename,
                video_id,
                title,
                privacy_status,
                status,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_recent_uploads(limit=25):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM upload_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_trend_snapshots(channel_key, items):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO trend_snapshots
                (channel_key, region, video_id, title, channel_title, views, views_per_hour, published_at, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_key,
                    item.get("region", "US"),
                    item["video_id"],
                    item["title"],
                    item.get("channel_title", ""),
                    item.get("views", 0),
                    item.get("views_per_hour", 0.0),
                    item.get("published_at", ""),
                    now,
                ),
            )
