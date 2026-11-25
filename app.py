from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ai_strategist import generate_video_plan
from config import CHANNELS, DEFAULT_PRIVACY, STUDIO_PIN
from db import get_recent_uploads, init_db, save_trend_snapshots
from progress_state import get_progress, request_pause, reset_progress, resume_progress, set_progress
from scheduler import process_next_queued_video, start_scheduler
from youtube_client import (
    fetch_channel_analytics,
    fetch_english_trends,
    get_channel_profile,
    get_credentials,
    bootstrap_secrets_from_env,
    is_connected,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_secrets_from_env()
    init_db()
    start_scheduler()
    yield


app = FastAPI(title="YouTube Automation Studio", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


def require_auth(request: Request):
    if STUDIO_PIN and request.cookies.get("studio_pin") != STUDIO_PIN:
        raise HTTPException(status_code=401, detail="PIN required")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if not STUDIO_PIN:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
def login_submit(request: Request, pin: str = Form(...)):
    if pin == STUDIO_PIN:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("studio_pin", STUDIO_PIN, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid PIN"})


@app.get("/manifest.json")
def pwa_manifest():
    return JSONResponse(
        {
            "name": "YouTube Studio Controller",
            "short_name": "YT Studio",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0f172a",
            "theme_color": "#0f172a",
        }
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if STUDIO_PIN and request.cookies.get("studio_pin") != STUDIO_PIN:
        return RedirectResponse("/login", status_code=303)

    channel_cards = {}
    for key, cfg in CHANNELS.items():
        connected = is_connected(key)
        profile = get_channel_profile(key) if connected else None
        analytics = fetch_channel_analytics(key) if connected else None
        queued = sorted(
            [p.name for p in cfg["queue_dir"].iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}]
        )
        channel_cards[key] = {
            "label": cfg["label"],
            "made_for_kids": cfg["made_for_kids"],
            "connected": connected,
            "profile": profile,
            "analytics": analytics,
            "queued": queued,
        }
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "channels": channel_cards,
            "uploads": get_recent_uploads(),
        },
    )


@app.post("/connect/{channel_key}")
def connect_channel(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    get_credentials(channel_key, interactive=True)
    return RedirectResponse("/", status_code=303)


@app.post("/api/queue-upload/{channel_key}")
async def queue_from_mobile(
    channel_key: str,
    video: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    _: None = Depends(require_auth),
):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")

    cfg = CHANNELS[channel_key]
    safe_name = Path(video.filename or "mobile_video.mp4").name
    dest = cfg["queue_dir"] / safe_name
    dest.write_bytes(await video.read())

    if title.strip() or description.strip() or tags.strip():
        meta = {
            "title": title.strip() or dest.stem.replace("_", " ").title(),
            "description": description.strip(),
            "tags": [t.strip() for t in tags.split(",") if t.strip()] or cfg["default_keywords"],
            "privacy_status": DEFAULT_PRIVACY,
            "contains_synthetic_media": True,
        }
        dest.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return JSONResponse({"status": "queued", "filename": safe_name, "channel": channel_key})


@app.get("/api/trends/{channel_key}")
def api_trends(channel_key: str, q: str = "", cc_only: bool = False, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    trends = fetch_english_trends(channel_key, query=q.strip() or None, creative_commons_only=cc_only)
    save_trend_snapshots(channel_key, trends[:15])
    return JSONResponse({"trends": trends[:20]})


@app.post("/api/generate-plan/{channel_key}")
def api_generate_plan(channel_key: str, topic_hint: str = Form(""), _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    trends = fetch_english_trends(channel_key, query=topic_hint.strip() or None)
    plan = generate_video_plan(channel_key, trends, topic_hint=topic_hint)
    return JSONResponse({"plan": plan})


@app.post("/api/upload-now/{channel_key}")
def api_upload_now(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    return JSONResponse(process_next_queued_video(channel_key))


def _run_autopilot_bg(channel_key: str, topic_hint: str, ai_disclosure: bool):
    from auto_producer import produce_daily_video
    try:
        produced = produce_daily_video(channel_key, topic_hint=topic_hint)
        meta_path = CHANNELS[channel_key]["queue_dir"] / Path(produced["file"]).with_suffix(".json").name
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["contains_synthetic_media"] = ai_disclosure
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        set_progress(channel_key, 96, "Uploading to YouTube...", produced["title"], True)
        uploaded = process_next_queued_video(channel_key, auto_produce_if_empty=False)
        if uploaded.get("status") == "success":
            set_progress(channel_key, 100, "Done! Uploaded to YouTube.", produced["title"], False)
        else:
            set_progress(channel_key, 100, f"Finished: {uploaded.get('error', uploaded.get('status'))}", produced["title"], False)
    except Exception as exc:
        set_progress(channel_key, 0, f"Error: {exc}", topic_hint or "Auto-Pilot", False)


@app.post("/api/autopilot/{channel_key}")
def api_autopilot(
    channel_key: str,
    background_tasks: BackgroundTasks,
    topic_hint: str = Form(""),
    ai_disclosure: bool = Form(True),
    _: None = Depends(require_auth),
):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    set_progress(channel_key, 5, "Starting Auto-Pilot...", topic_hint.strip() or "Top English Trends", True)
    background_tasks.add_task(_run_autopilot_bg, channel_key, topic_hint, ai_disclosure)
    return JSONResponse({"status": "started", "channel": channel_key, "topic": topic_hint})


@app.get("/api/progress/{channel_key}")
def api_progress(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    return JSONResponse(get_progress(channel_key))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/cron-run")
def cron_run(pin: str = ""):
    if STUDIO_PIN and pin != STUDIO_PIN:
        raise HTTPException(401, "Invalid PIN")
    from scheduler import run_daily_jobs
    run_daily_jobs()
    return {"status": "completed"}


def _run_batch_task(channel_key: str, count: int, topic_hint: str = ""):
    from auto_producer import produce_daily_video
    for i in range(count):
        try:
            set_progress(channel_key, 5, f"Batch {i + 1}/{count}: starting...", topic_hint or "Top English Trends", True)
            res = produce_daily_video(channel_key, topic_hint=topic_hint)
            set_progress(channel_key, 96, f"Batch {i + 1}/{count}: uploading...", res["title"], True)
            process_next_queued_video(channel_key, auto_produce_if_empty=False)
        except Exception as exc:
            print(f"[batch] {channel_key} error: {exc}")
    set_progress(channel_key, 100, f"Batch of {count} finished!", topic_hint or "Batch Complete", False)


@app.post("/api/autopilot-batch/{channel_key}")
def api_autopilot_batch(
    channel_key: str,
    background_tasks: BackgroundTasks,
    count: int = 5,
    topic_hint: str = Form(""),
    _: None = Depends(require_auth),
):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    count = max(1, min(count, 10))
    background_tasks.add_task(_run_batch_task, channel_key, count, topic_hint)
    return JSONResponse({"status": "started", "channel": channel_key, "count": count})


@app.post("/api/produce-only/{channel_key}")
def api_produce_only(
    channel_key: str,
    topic_hint: str = Form(""),
    ai_disclosure: bool = Form(True),
    _: None = Depends(require_auth),
):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    from auto_producer import produce_daily_video
    res = produce_daily_video(channel_key, topic_hint=topic_hint)
    meta_path = CHANNELS[channel_key]["queue_dir"] / Path(res["file"]).with_suffix(".json").name
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["contains_synthetic_media"] = ai_disclosure
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return JSONResponse(res)


@app.post("/api/pause/{channel_key}")
def api_pause(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    return JSONResponse(request_pause(channel_key))


@app.post("/api/continue/{channel_key}")
async def api_continue(channel_key: str, request: Request, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    updated_plan = None
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("plan"):
            updated_plan = body["plan"]
    except Exception:
        pass
    return JSONResponse(resume_progress(channel_key, updated_plan=updated_plan))


@app.get("/media/{channel_key}/{filename}")
def serve_channel_media(channel_key: str, filename: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    safe = Path(filename).name
    for folder in (CHANNELS[channel_key]["queue_dir"], CHANNELS[channel_key]["uploaded_dir"]):
        candidate = folder / safe
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(404, "Media not found")


@app.get("/work/{job_name}/{filename}")
def serve_work_preview(job_name: str, filename: str, _: None = Depends(require_auth)):
    from auto_producer import WORK_DIR
    candidate = WORK_DIR / Path(job_name).name / Path(filename).name
    if candidate.exists():
        return FileResponse(candidate)
    raise HTTPException(404, "Preview not found")


@app.get("/api/my-videos/{channel_key}")
def api_my_videos(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    from youtube_client import list_my_videos
    return JSONResponse({"videos": list_my_videos(channel_key)})


@app.post("/api/improve-video/{channel_key}/{video_id}")
def api_improve_video(channel_key: str, video_id: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    from youtube_client import list_my_videos
    from ai_strategist import improve_old_video_seo
    vids = [v for v in list_my_videos(channel_key, max_results=30) if v["id"] == video_id]
    if not vids:
        raise HTTPException(404, "Video not found on channel")
    return JSONResponse({"suggestion": improve_old_video_seo(channel_key, vids[0]), "video": vids[0]})


@app.post("/api/apply-video-seo/{channel_key}/{video_id}")
async def api_apply_video_seo(channel_key: str, video_id: str, request: Request, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    from youtube_client import update_video_metadata
    body = await request.json()
    res = update_video_metadata(
        channel_key,
        video_id,
        title=body["title"],
        description=body.get("description", ""),
        tags=body.get("tags", []),
    )
    return JSONResponse({"status": "updated", "video": res})


@app.get("/api/channel-audit/{channel_key}")
def api_channel_audit(channel_key: str, _: None = Depends(require_auth)):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    from youtube_client import list_my_videos
    from ai_strategist import audit_channel_growth
    analytics = fetch_channel_analytics(channel_key)
    videos = list_my_videos(channel_key)
    return JSONResponse({"audit": audit_channel_growth(channel_key, analytics, videos)})


def _run_viral_agent_bg(channel_key: str, ai_disclosure: bool):
    from youtube_client import list_my_videos, update_video_metadata
    from ai_strategist import audit_channel_growth, improve_old_video_seo
    from auto_producer import produce_daily_video
    try:
        set_progress(channel_key, 8, "Agent: reading channel analytics & old videos...", "Viral AI Agent", True)
        analytics = fetch_channel_analytics(channel_key)
        videos = list_my_videos(channel_key, max_results=15)

        set_progress(channel_key, 20, "Agent: auditing bottlenecks & winning topics...", "Viral AI Agent", True)
        audit = audit_channel_growth(channel_key, analytics, videos)
        best_idea = (audit.get("next_5_video_ideas") or [""])[0]

        # Upgrade up to 2 lowest-view old videos automatically
        low_vids = sorted(videos, key=lambda v: v.get("views", 0))[:2]
        for idx, v in enumerate(low_vids):
            try:
                set_progress(channel_key, 30 + idx * 10, f"Agent: optimizing old video '{v['title'][:30]}'...", best_idea or v["title"], True)
                seo = improve_old_video_seo(channel_key, v)
                update_video_metadata(channel_key, v["id"], seo["title"], seo["description"], seo.get("tags", []))
            except Exception as exc:
                print(f"[viral-agent] SEO update skipped: {exc}")

        # Produce & upload 1 high-CTR viral video on the top audited idea
        produced = produce_daily_video(channel_key, topic_hint=best_idea)
        meta_path = CHANNELS[channel_key]["queue_dir"] / Path(produced["file"]).with_suffix(".json").name
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["contains_synthetic_media"] = ai_disclosure
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        set_progress(channel_key, 96, "Agent: uploading new viral video...", produced["title"], True)
        uploaded = process_next_queued_video(channel_key, auto_produce_if_empty=False)
        status_msg = "Done! Optimized old videos & uploaded new viral Short." if uploaded.get("status") == "success" else f"Finished: {uploaded.get('error', uploaded.get('status'))}"
        set_progress(channel_key, 100, status_msg, produced["title"], False)
    except Exception as exc:
        set_progress(channel_key, 0, f"Error: {exc}", "Viral AI Agent", False)


@app.post("/api/viral-agent/{channel_key}")
def api_viral_agent(
    channel_key: str,
    background_tasks: BackgroundTasks,
    ai_disclosure: bool = Form(True),
    _: None = Depends(require_auth),
):
    if channel_key not in CHANNELS:
        raise HTTPException(404, "Unknown channel")
    set_progress(channel_key, 5, "Starting Viral AI Agent...", "Full Channel Growth Cycle", True)
    background_tasks.add_task(_run_viral_agent_bg, channel_key, ai_disclosure)
    return JSONResponse({"status": "started", "channel": channel_key})
