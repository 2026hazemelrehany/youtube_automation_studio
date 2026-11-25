import json
import os
import shutil
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

from auto_producer import produce_daily_video
from config import CHANNELS, DEFAULT_PRIVACY
from db import log_upload
from youtube_client import is_connected, upload_video

scheduler = BackgroundScheduler(timezone="UTC")

# Default: 5 spaced uploads per day (09:00, 12:00, 15:00, 18:00, 21:00 UTC)
POST_HOURS_UTC = os.getenv("POST_HOURS_UTC", "9,12,15,18,21")
DAILY_POST_MINUTE_UTC = int(os.getenv("DAILY_POST_MINUTE_UTC", "0"))


def process_next_queued_video(channel_key: str, auto_produce_if_empty: bool = False) -> dict:
    if not is_connected(channel_key):
        return {"status": "skipped", "reason": "Channel not connected"}

    cfg = CHANNELS[channel_key]
    q_dir: Path = cfg["queue_dir"]
    videos = sorted(
        [p for p in q_dir.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}]
    )
    if not videos and auto_produce_if_empty:
        produce_daily_video(channel_key)
        videos = sorted(
            [p for p in q_dir.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}]
        )

    if not videos:
        return {"status": "empty", "reason": "No videos in queue"}

    video_path = videos[0]
    meta_path = video_path.with_suffix(".json")
    thumb_path = video_path.with_suffix(".jpg")
    if not thumb_path.exists():
        thumb_path = video_path.with_suffix(".png")

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {
            "title": video_path.stem.replace("_", " ").title(),
            "description": f"Daily upload for {cfg['label']}.",
            "tags": cfg["default_keywords"],
            "privacy_status": DEFAULT_PRIVACY,
            "contains_synthetic_media": True,
        }

    try:
        vid_id = upload_video(
            channel_key=channel_key,
            video_path=str(video_path),
            title=meta["title"],
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            privacy_status=meta.get("privacy_status", DEFAULT_PRIVACY),
            contains_synthetic_media=meta.get("contains_synthetic_media", True),
            thumbnail_path=str(thumb_path) if thumb_path.exists() else None,
        )
        shutil.move(str(video_path), str(cfg["uploaded_dir"] / video_path.name))
        if meta_path.exists():
            shutil.move(str(meta_path), str(cfg["uploaded_dir"] / meta_path.name))
        if thumb_path.exists():
            shutil.move(str(thumb_path), str(cfg["uploaded_dir"] / thumb_path.name))

        log_upload(
            channel_key,
            video_path.name,
            vid_id,
            meta["title"],
            meta.get("privacy_status", DEFAULT_PRIVACY),
            "success",
        )
        return {"status": "success", "video_id": vid_id, "title": meta["title"]}
    except Exception as exc:
        log_upload(channel_key, video_path.name, None, meta.get("title", ""), DEFAULT_PRIVACY, "error", str(exc))
        return {"status": "error", "error": str(exc)}


def run_daily_jobs():
    for key in CHANNELS:
        process_next_queued_video(key, auto_produce_if_empty=True)


def start_scheduler():
    if not scheduler.running:
        hours = ",".join(h.strip() for h in POST_HOURS_UTC.split(",") if h.strip()) or "9,12,15,18,21"
        scheduler.add_job(
            run_daily_jobs,
            "cron",
            hour=hours,
            minute=DAILY_POST_MINUTE_UTC,
            id="daily_youtube_post",
            replace_existing=True,
        )
        scheduler.start()