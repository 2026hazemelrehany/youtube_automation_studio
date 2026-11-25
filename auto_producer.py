import asyncio
import json
import os
import random
import subprocess
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import edge_tts
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

from config import CHANNELS, DEFAULT_PRIVACY, GEMINI_API_KEY
from progress_state import set_progress, wait_if_paused
from youtube_client import fetch_english_trends

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
WORK_DIR = BASE_DIR / "work"
ASSETS_DIR.mkdir(exist_ok=True)
WORK_DIR.mkdir(exist_ok=True)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
USE_AI_IMAGES = os.getenv("USE_AI_IMAGES", "false").lower() == "true"

FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
]

_OPENVERSE_DISABLED = False
_WIKIMEDIA_DISABLED = False


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["impact.ttf", "arialbd.ttf", "segoeuib.ttf", "calibrib.ttf"]
        if bold
        else ["arial.ttf", "segoeui.ttf", "calibri.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _local_trend_fallback(channel_key: str, trends: list[dict]) -> dict:
    cfg = CHANNELS[channel_key]
    top = trends[:3] or [{"title": "Today's Top Viral Story", "channel_title": "Creators", "tags": cfg["default_keywords"]}]
    main_title = top[0]["title"][:45].strip()
    default_q = "cartoon" if cfg["made_for_kids"] else "gaming"
    colors = ["#1e1b4b", "#0f172a", "#172554", "#312e81", "#0c4a6e"]

    scenes = [
        {
            "headline": "WAIT UNTIL YOU SEE THIS",
            "narration": f"Everyone is talking about {main_title} today, and here is why.",
            "stock_keyword": default_q,
            "bg_hex": colors[0],
        }
    ]
    for idx, item in enumerate(top):
        t = item["title"]
        scenes.append(
            {
                "headline": t[:26].upper(),
                "narration": f"Trend number {idx + 1} is {t}, getting huge views right now.",
                "stock_keyword": default_q,
                "bg_hex": colors[(idx + 1) % len(colors)],
            }
        )
    while len(scenes) < 5:
        scenes.append(
            {
                "headline": "SUBSCRIBE FOR MORE",
                "narration": "Follow for daily trending updates.",
                "stock_keyword": default_q,
                "bg_hex": colors[len(scenes) % len(colors)],
            }
        )

    return {
        "title": f"{main_title} #Shorts",
        "description": f"Fast breakdown for {cfg['label']}. #Shorts #Trending",
        "tags": top[0].get("tags", [])[:10] or cfg["default_keywords"],
        "scenes": scenes[:5],
    }


def _generate_scenes_script(channel_key: str, trends: list[dict], topic_hint: str = "") -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    cfg = CHANNELS[channel_key]
    client = genai.Client(api_key=GEMINI_API_KEY)
    top_trends = [
        {"title": t["title"], "views_per_hour": t["views_per_hour"], "tags": t["tags"]}
        for t in trends[:8]
    ]

    style = (
        "Kids storytelling / fun fact for 'Little Wonder World' (bright, joyful, COPPA-safe)."
        if cfg["made_for_kids"]
        else "High-energy Games & Movies commentary or breakdown (dramatic, curiosity-driven)."
    )

    prompt = f"""
Create a fast 25-30 second vertical YouTube Short (9:16) for US/UK/CA/AU viewers.
Channel: {cfg['label']}
Style: {style}
Topic: {topic_hint or 'Pick the strongest viral angle from these trends'}

Trends:
{json.dumps(top_trends, indent=2)}

Return ONLY valid JSON with:
- "title": clickable title under 65 chars (include #Shorts)
- "description": SEO description (2 sentences + hashtags)
- "tags": list of 10 English tags
- "scenes": list of exactly 5 scenes, each with:
    - "headline": 2-4 word caption (ALL CAPS)
    - "narration": 10-14 spoken words
    - "stock_keyword": 1-2 concrete nouns (e.g. "sports car", "cinema", "dinosaur")
    - "bg_hex": dark rich hex color like "#1e1b4b"
"""

    for model_name in FALLBACK_MODELS:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text)
        except Exception:
            continue

    return _local_trend_fallback(channel_key, trends)


def _fetch_openverse_image(query: str, out_img: Path) -> bool:
    global _OPENVERSE_DISABLED
    if _OPENVERSE_DISABLED:
        return False
    try:
        url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({"q": query, "page_size": 3})
        req = urllib.request.Request(url, headers={"User-Agent": "YouTubeAutomationStudio/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("results", []):
            img_url = item.get("url", "")
            if not img_url:
                continue
            dl_req = urllib.request.Request(img_url, headers={"User-Agent": "YouTubeAutomationStudio/1.0"})
            with urllib.request.urlopen(dl_req, timeout=4) as dl:
                out_img.write_bytes(dl.read())
            Image.open(out_img).verify()
            if out_img.stat().st_size > 5000:
                return True
    except Exception:
        _OPENVERSE_DISABLED = True
    return False


def _fetch_wikimedia_image(query: str, out_img: Path) -> bool:
    global _WIKIMEDIA_DISABLED
    if _WIKIMEDIA_DISABLED:
        return False
    short_q = " ".join(query.split()[:2]) or "cinema"
    try:
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrnamespace": "6",
                "gsrsearch": short_q,
                "gsrlimit": "3",
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "format": "json",
            }
        )
        req = urllib.request.Request(url, headers={"User-Agent": "YouTubeAutomationStudio/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for p in (data.get("query") or {}).get("pages", {}).values():
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("mime") in {"image/jpeg", "image/png"} and info.get("url"):
                dl_req = urllib.request.Request(info["url"], headers={"User-Agent": "YouTubeAutomationStudio/1.0"})
                with urllib.request.urlopen(dl_req, timeout=4) as dl:
                    out_img.write_bytes(dl.read())
                if out_img.stat().st_size > 5000:
                    return True
    except Exception:
        _WIKIMEDIA_DISABLED = True
    return False


def _fetch_yt_cc_thumbnail(video_id: str, out_img: Path) -> bool:
    for qname in ("maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"):
        try:
            url = f"https://i.ytimg.com/vi/{video_id}/{qname}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                out_img.write_bytes(resp.read())
            if out_img.exists() and out_img.stat().st_size > 5000:
                return True
        except Exception:
            continue
    return False


def _download_cc_montage_clips(channel_key: str, query: str, job_dir: Path, fallback_kw: str = "") -> tuple[list[Path], list[str], list[str]]:
    local_dir = ASSETS_DIR / channel_key
    if local_dir.exists() and any(p.suffix.lower() in {".mp4", ".mov", ".mkv"} for p in local_dir.iterdir()):
        return [], [], []

    search_q = " ".join((query or "").replace("#Shorts", "").split()[:3]) or CHANNELS[channel_key]["default_keywords"][0]
    cc_videos = fetch_english_trends(channel_key, query=search_q, creative_commons_only=True)
    if not cc_videos and fallback_kw:
        cc_videos = fetch_english_trends(channel_key, query=fallback_kw, creative_commons_only=True)
    if not cc_videos:
        cc_videos = fetch_english_trends(channel_key, query=CHANNELS[channel_key]["default_keywords"][0], creative_commons_only=True)

    downloaded: list[Path] = []
    credits: list[str] = []
    cc_ids: list[str] = [v["video_id"] for v in cc_videos if v.get("video_id")]
    for i, item in enumerate(cc_videos[:2]):
        out_mp4 = job_dir / f"cc_{i}.mp4"
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    "--no-playlist",
                    "-f",
                    "best[height<=480][ext=mp4]/mp4",
                    "--max-filesize",
                    "15M",
                    "-o",
                    str(out_mp4),
                    item["url"],
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            if out_mp4.exists() and out_mp4.stat().st_size > 10000:
                downloaded.append(out_mp4)
                credits.append(f"{item['channel_title']}: {item['url']}")
        except Exception as exc:
            print(f"[auto_producer] yt-dlp CC skip: {exc}")
    return downloaded, credits, cc_ids


def _pick_local_broll(channel_key: str, index: int) -> Path | None:
    folder = ASSETS_DIR / channel_key
    if not folder.exists():
        return None
    clips = sorted([p for p in folder.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}])
    if not clips:
        return None
    return clips[index % len(clips)]


async def _tts_async(text: str, voice: str, out_mp3: Path):
    communicate = edge_tts.Communicate(text, voice, rate="+10%")
    await communicate.save(str(out_mp3))


def _synthesize_voice(text: str, channel_key: str, out_mp3: Path):
    voice = "en-US-AnaNeural" if CHANNELS[channel_key]["made_for_kids"] else "en-US-AndrewMultilingualNeural"
    try:
        asyncio.run(_tts_async(text, voice, out_mp3))
    except Exception:
        fallback = "en-US-AriaNeural" if CHANNELS[channel_key]["made_for_kids"] else "en-US-ChristopherNeural"
        asyncio.run(_tts_async(text, fallback, out_mp3))


def _get_audio_duration(audio_path: Path) -> float:
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(res.stdout.strip())


def _draw_viral_caption(overlay: Image.Image, headline: str):
    w, h = overlay.size
    draw = ImageDraw.Draw(overlay)
    for row in range(1180, h, 2):
        alpha = int(min(215, ((row - 1180) / (h - 1180)) * 235))
        draw.line([(0, row), (w, row), (0, row + 1), (w, row + 1)], fill=(8, 12, 24, alpha))

    font = _load_font(86, bold=True)
    lines = textwrap.wrap(headline.upper(), width=14)[:3]
    y = 1360
    for idx, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (w - (bbox[2] - bbox[0])) // 2
        color = (250, 204, 21, 255) if idx == 0 else (255, 255, 255, 255)
        draw.text((x, y), line, fill=color, font=font, stroke_width=7, stroke_fill=(0, 0, 0, 255))
        y += 98


def _render_caption_overlay(headline: str, out_png: Path):
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    _draw_viral_caption(img, headline)
    img.save(out_png)


def _compose_image_with_caption(bg_path: Path, headline: str, out_png: Path):
    w, h = 1080, 1920
    bg = Image.open(bg_path).convert("RGB")
    scale = max(w / bg.width, h / bg.height)
    nw, nh = int(bg.width * scale), int(bg.height * scale)
    bg = bg.resize((nw, nh), Image.Resampling.BILINEAR)
    bg = bg.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h)).convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _draw_viral_caption(overlay, headline)
    Image.alpha_composite(bg, overlay).convert("RGB").save(out_png)


def _render_scene_card(headline: str, bg_hex: str, out_png: Path):
    img = Image.new("RGBA", (1080, 1920), bg_hex if bg_hex.startswith("#") and len(bg_hex) == 7 else "#0f172a")
    _draw_viral_caption(img, headline)
    img.convert("RGB").save(out_png)


def _render_thumbnail(title: str, out_jpg: Path, made_for_kids: bool):
    w, h = 1280, 720
    bg = Image.new("RGBA", (w, h), "#1d4ed8" if made_for_kids else "#111827")
    draw = ImageDraw.Draw(bg)
    draw.rectangle([0, 640, w, h], fill="#f59e0b")
    font = _load_font(84, bold=True)
    lines = textwrap.wrap(title.replace("#Shorts", "").strip().upper(), width=18)[:2]
    y = 220
    for idx, line in enumerate(lines):
        color = (250, 204, 21, 255) if idx == 0 else (255, 255, 255, 255)
        draw.text((64, y), line, fill=color, font=font, stroke_width=6, stroke_fill=(0, 0, 0, 255))
        y += 96
    bg.convert("RGB").save(out_jpg, quality=90)


def produce_daily_video(channel_key: str, topic_hint: str = "") -> dict:
    cfg = CHANNELS[channel_key]
    chosen_topic = topic_hint.strip() or "Top English Trends"
    set_progress(channel_key, 10, "Scanning English trends...", chosen_topic, True)
    trends = fetch_english_trends(channel_key, query=topic_hint.strip() or None)

    wait_if_paused(channel_key)
    set_progress(channel_key, 25, "Writing script & SEO...", chosen_topic, True)
    plan = _generate_scenes_script(channel_key, trends, topic_hint=topic_hint)
    chosen_topic = plan.get("title", chosen_topic)
    set_progress(channel_key, 32, "Script & scenes ready", chosen_topic, True, plan=plan)

    edited, new_plan = wait_if_paused(channel_key)
    if edited and new_plan:
        plan = new_plan
        chosen_topic = plan.get("title", chosen_topic)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_dir = WORK_DIR / f"{channel_key}_{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)

    scenes = plan.get("scenes", [])
    if not scenes:
        raise RuntimeError("AI returned no scenes")

    full_narration = " ".join(s["narration"] for s in scenes)
    audio_path = job_dir / "voice.mp3"
    set_progress(channel_key, 40, "Generating voiceover...", chosen_topic, True)
    _synthesize_voice(full_narration, channel_key, audio_path)
    duration = max(_get_audio_duration(audio_path), 10.0)
    per_scene = duration / len(scenes)

    set_progress(channel_key, 45, "Fetching video clip...", chosen_topic, True)
    first_kw = scenes[0].get("stock_keyword", "") if scenes else ""
    cc_clips, cc_credits, cc_ids = _download_cc_montage_clips(channel_key, topic_hint.strip() or chosen_topic, job_dir, fallback_kw=first_kw)

    clip_paths = []
    idx = 0
    while idx < len(scenes):
        edited, new_plan = wait_if_paused(channel_key)
        if edited and new_plan:
            plan = new_plan
            chosen_topic = plan.get("title", chosen_topic)
            scenes = plan.get("scenes", scenes)
            full_narration = " ".join(s["narration"] for s in scenes)
            _synthesize_voice(full_narration, channel_key, audio_path)
            duration = max(_get_audio_duration(audio_path), 10.0)
            per_scene = duration / max(len(scenes), 1)
            clip_paths = []
            idx = 0
            set_progress(channel_key, 42, "Rebuilding with your edits...", chosen_topic, True, plan=plan)
            continue

        sc = scenes[idx]
        pct = 48 + int(((idx + 1) / max(len(scenes), 1)) * 38)
        set_progress(channel_key, pct, f"Building scene {idx + 1}/{len(scenes)}: {sc.get('headline', '')}", chosen_topic, True)

        clip_path = job_dir / f"scene_{idx}.mp4"
        source_video = cc_clips[idx % len(cc_clips)] if cc_clips else _pick_local_broll(channel_key, idx)

        if source_video and source_video.exists():
            overlay_png = job_dir / f"overlay_{idx}.png"
            _render_caption_overlay(sc.get("headline", ""), overlay_png)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str((idx * 4) % 16),
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(source_video),
                    "-i",
                    str(overlay_png),
                    "-t",
                    f"{per_scene:.2f}",
                    "-filter_complex",
                    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[bg][1:v]overlay=0:0[out]",
                    "-map",
                    "[out]",
                    "-an",
                    "-r",
                    "24",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip_path),
                ],
                check=True,
                capture_output=True,
            )
            preview_src = overlay_png
        else:
            raw_img = job_dir / f"raw_{idx}.png"
            png_path = job_dir / f"scene_{idx}.png"
            kw = sc.get("stock_keyword") or "cinema"
            yt_cc_id = cc_ids[idx % len(cc_ids)] if cc_ids else ""
            has_img = (
                _fetch_openverse_image(kw, raw_img)
                or _fetch_wikimedia_image(kw, raw_img)
                or (bool(yt_cc_id) and _fetch_yt_cc_thumbnail(yt_cc_id, raw_img))
            )
            if has_img:
                _compose_image_with_caption(raw_img, sc.get("headline", ""), png_path)
            else:
                _render_scene_card(sc.get("headline", ""), sc.get("bg_hex", "#0f172a"), png_path)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(png_path),
                    "-t",
                    f"{per_scene:.2f}",
                    "-r",
                    "24",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "stillimage",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip_path),
                ],
                check=True,
                capture_output=True,
            )
            preview_src = png_path

        set_progress(
            channel_key,
            pct,
            f"Rendered scene {idx + 1}/{len(scenes)}",
            chosen_topic,
            True,
            preview_image=f"/work/{job_dir.name}/{preview_src.name}",
        )
        clip_paths.append(clip_path)
        idx += 1

    wait_if_paused(channel_key)
    set_progress(channel_key, 88, "Combining video & audio...", chosen_topic, True)
    concat_txt = job_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths), encoding="utf-8")

    out_video = cfg["queue_dir"] / f"auto_{stamp}.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_video),
        ],
        check=True,
        capture_output=True,
    )

    _render_thumbnail(plan["title"], out_video.with_suffix(".jpg"), cfg["made_for_kids"])
    meta = {
        "title": plan["title"],
        "description": plan["description"] + ("\n\nCreative Commons Sources:\n" + "\n".join(cc_credits) if cc_credits else ""),
        "tags": plan.get("tags", cfg["default_keywords"]),
        "privacy_status": DEFAULT_PRIVACY,
        "contains_synthetic_media": True,
    }
    out_video.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    set_progress(channel_key, 94, "Video ready — preview below", chosen_topic, True, video_url=f"/media/{channel_key}/{out_video.name}")
    return {"status": "produced", "file": out_video.name, "title": plan["title"]}