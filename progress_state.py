import copy
import threading
import time

_LOCK = threading.Lock()
_STATE: dict[str, dict] = {}
_EVENTS: dict[str, threading.Event] = {}


def _get_event(channel_key: str) -> threading.Event:
    ev = _EVENTS.get(channel_key)
    if ev is None:
        ev = threading.Event()
        ev.set()  # not paused by default
        _EVENTS[channel_key] = ev
    return ev


def reset_progress(channel_key: str, topic: str = ""):
    with _LOCK:
        ev = _get_event(channel_key)
        ev.set()
        _STATE[channel_key] = {
            "active": True,
            "paused": False,
            "percent": 5,
            "message": "Starting...",
            "topic": topic,
            "started_at": time.time(),
            "elapsed_seconds": 0,
            "eta_seconds": 45,
            "steps_log": ["Starting Auto-Pilot..."],
            "plan": None,
            "plan_edited": False,
            "preview_images": [],
            "video_url": "",
        }


def set_progress(
    channel_key: str,
    percent: int,
    message: str,
    topic: str = "",
    active: bool = True,
    plan: dict | None = None,
    preview_image: str = "",
    video_url: str = "",
):
    with _LOCK:
        now = time.time()
        prev = _STATE.get(channel_key)
        if not prev or not prev.get("active") or percent <= 5:
            started_at = now
            steps_log = []
        else:
            started_at = prev.get("started_at", now)
            steps_log = list(prev.get("steps_log", []))

        if not steps_log or steps_log[-1] != message:
            steps_log.append(message)

        elapsed = max(0, int(now - started_at))
        if active and 5 < percent < 100 and elapsed > 0:
            total_est = elapsed / (percent / 100.0)
            eta_seconds = max(1, int(total_est - elapsed))
        elif not active:
            eta_seconds = 0
        else:
            eta_seconds = 45

        _STATE[channel_key] = {
            "active": active,
            "paused": prev.get("paused", False) if prev and active else False,
            "percent": max(0, min(100, int(percent))),
            "message": message,
            "topic": topic or (prev.get("topic", "") if prev else ""),
            "started_at": started_at,
            "elapsed_seconds": elapsed,
            "eta_seconds": eta_seconds,
            "steps_log": steps_log[-12:],
            "plan": copy.deepcopy(plan) if plan is not None else (prev.get("plan") if prev else None),
            "plan_edited": prev.get("plan_edited", False) if prev else False,
            "preview_images": (list(prev.get("preview_images", [])) if prev and percent > 5 else [])
            + ([preview_image] if preview_image else []),
            "video_url": video_url or (prev.get("video_url", "") if prev and percent > 5 else ""),
        }


def request_pause(channel_key: str) -> dict:
    with _LOCK:
        ev = _get_event(channel_key)
        ev.clear()
        st = _STATE.get(channel_key)
        if st:
            st["paused"] = True
            if "Paused for editing" not in st["steps_log"][-1:]:
                st["steps_log"].append("Paused — ready to edit or continue")
        return copy.deepcopy(st) if st else {}


def resume_progress(channel_key: str, updated_plan: dict | None = None) -> dict:
    with _LOCK:
        st = _STATE.get(channel_key)
        if st:
            st["paused"] = False
            if updated_plan is not None:
                st["plan"] = copy.deepcopy(updated_plan)
                st["plan_edited"] = True
                if updated_plan.get("title"):
                    st["topic"] = updated_plan["title"]
                st["steps_log"].append("Saved your edits — continuing...")
            else:
                st["steps_log"].append("Continuing...")
        ev = _get_event(channel_key)
        ev.set()
        return copy.deepcopy(st) if st else {}


def wait_if_paused(channel_key: str) -> tuple[bool, dict | None]:
    """Blocks while paused. Returns (was_edited, latest_plan)."""
    ev = _get_event(channel_key)
    ev.wait()
    with _LOCK:
        st = _STATE.get(channel_key)
        if not st:
            return False, None
        edited = bool(st.get("plan_edited"))
        st["plan_edited"] = False
        return edited, copy.deepcopy(st.get("plan"))


def get_progress(channel_key: str) -> dict:
    with _LOCK:
        st = _STATE.get(channel_key)
        if not st:
            return {
                "active": False,
                "paused": False,
                "percent": 0,
                "message": "Idle",
                "topic": "",
                "elapsed_seconds": 0,
                "eta_seconds": 0,
                "steps_log": [],
                "plan": None,
                "preview_images": [],
                "video_url": "",
            }
        data = copy.deepcopy(st)
        if data["active"] and not data.get("paused") and 5 < data["percent"] < 100:
            elapsed = max(1, int(time.time() - data.get("started_at", time.time())))
            data["elapsed_seconds"] = elapsed
            total_est = elapsed / (data["percent"] / 100.0)
            data["eta_seconds"] = max(1, int(total_est - elapsed))
        return data
