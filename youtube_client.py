import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import (
    CHANNELS,
    CLIENT_SECRET_FILE,
    ENGLISH_REGIONS,
    RELEVANCE_LANGUAGE,
    SCOPES,
)


def get_credentials(channel_key: str, interactive: bool = False) -> Credentials | None:
    cfg = CHANNELS[channel_key]
    token_path: Path = cfg["token_file"]
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if creds and creds.valid:
        return creds

    if not interactive:
        return None

    if not Path(CLIENT_SECRET_FILE).exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRET_FILE}. Download OAuth Desktop credentials from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def is_connected(channel_key: str) -> bool:
    return get_credentials(channel_key, interactive=False) is not None


def get_services(channel_key: str):
    creds = get_credentials(channel_key, interactive=False)
    if not creds:
        raise RuntimeError(f"Channel '{channel_key}' is not connected. Authorize it first.")
    yt = build("youtube", "v3", credentials=creds)
    yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
    return yt, yt_analytics


def get_channel_profile(channel_key: str) -> dict | None:
    if not is_connected(channel_key):
        return None
    yt, _ = get_services(channel_key)
    resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return None
    ch = items[0]
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "views": int(ch["statistics"].get("viewCount", 0)),
        "videos": int(ch["statistics"].get("videoCount", 0)),
    }


def _calc_views_per_hour(views: int, published_iso: str) -> float:
    try:
        pub = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        hours = max((datetime.now(timezone.utc) - pub).total_seconds() / 3600.0, 1.0)
        return round(views / hours, 1)
    except Exception:
        return 0.0


def fetch_english_trends(
    channel_key: str,
    query: str | None = None,
    creative_commons_only: bool = False,
    max_per_region: int = 8,
) -> list[dict]:
    yt, _ = get_services(channel_key)
    cfg = CHANNELS[channel_key]
    results = []
    seen_ids = set()

    if query:
        search_params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "viewCount",
            "relevanceLanguage": RELEVANCE_LANGUAGE,
            "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(),
            "maxResults": 15,
        }
        if creative_commons_only:
            search_params["videoLicense"] = "creativeCommon"

        search_resp = yt.search().list(**search_params).execute()
        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
        if video_ids:
            vid_resp = yt.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute()
            for v in vid_resp.get("items", []):
                vid = v["id"]
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                views = int(v.get("statistics", {}).get("viewCount", 0))
                pub = v["snippet"]["publishedAt"]
                results.append(
                    {
                        "region": "EN-Global",
                        "video_id": vid,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "title": v["snippet"]["title"],
                        "channel_title": v["snippet"]["channelTitle"],
                        "views": views,
                        "views_per_hour": _calc_views_per_hour(views, pub),
                        "published_at": pub,
                        "tags": v["snippet"].get("tags", [])[:10],
                    }
                )
    else:
        for region in ENGLISH_REGIONS:
            for cat_id in cfg["trend_categories"][:2]:
                resp = (
                    yt.videos()
                    .list(
                        part="snippet,statistics",
                        chart="mostPopular",
                        regionCode=region,
                        videoCategoryId=cat_id,
                        maxResults=max_per_region,
                    )
                    .execute()
                )
                for v in resp.get("items", []):
                    vid = v["id"]
                    if vid in seen_ids:
                        continue
                    seen_ids.add(vid)
                    views = int(v.get("statistics", {}).get("viewCount", 0))
                    pub = v["snippet"]["publishedAt"]
                    results.append(
                        {
                            "region": region,
                            "video_id": vid,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "title": v["snippet"]["title"],
                            "channel_title": v["snippet"]["channelTitle"],
                            "views": views,
                            "views_per_hour": _calc_views_per_hour(views, pub),
                            "published_at": pub,
                            "tags": v["snippet"].get("tags", [])[:10],
                        }
                    )

    results.sort(key=lambda x: x["views_per_hour"], reverse=True)
    return results


def fetch_channel_analytics(channel_key: str, days: int = 28) -> dict:
    _, yt_analytics = get_services(channel_key)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    resp = (
        yt_analytics.reports()
        .query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
        )
        .execute()
    )
    rows = resp.get("rows", [])
    if not rows:
        return {"views": 0, "watch_minutes": 0, "avg_view_sec": 0, "subs_gained": 0}
    r = rows[0]
    return {
        "views": int(r[0]),
        "watch_minutes": int(r[1]),
        "avg_view_sec": int(r[2]),
        "subs_gained": int(r[3]),
    }


def upload_video(
    channel_key: str,
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str = "private",
    contains_synthetic_media: bool = True,
    thumbnail_path: str | None = None,
) -> str:
    yt, _ = get_services(channel_key)
    cfg = CHANNELS[channel_key]

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": cfg["default_category_id"],
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": cfg["made_for_kids"],
            "containsSyntheticMedia": contains_synthetic_media,
        },
    }

    media = MediaFileUpload(video_path, chunksize=4 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()
        except Exception as exc:
            print(f"[youtube_client] Thumbnail skipped (enable Intermediate Features in YouTube Studio): {exc}")

    return video_id


def bootstrap_secrets_from_env():
    cs_json = os.getenv("CLIENT_SECRET_JSON", "").strip()
    if cs_json and not Path(CLIENT_SECRET_FILE).exists():
        Path(CLIENT_SECRET_FILE).write_text(cs_json, encoding="utf-8")
    env_map = {
        "kids": os.getenv("KIDS_TOKEN_JSON", "").strip(),
        "games_movies": os.getenv("GAMES_MOVIES_TOKEN_JSON", "").strip(),
    }
    for key, val in env_map.items():
        if val:
            tp = CHANNELS[key]["token_file"]
            if not tp.exists():
                tp.write_text(val, encoding="utf-8")


def list_my_videos(channel_key: str, max_results: int = 15) -> list[dict]:
    yt, _ = get_services(channel_key)
    ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch_resp.get("items", [])
    if not items:
        return []
    uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl_resp = yt.playlistItems().list(part="contentDetails", playlistId=uploads_pl, maxResults=max_results).execute()
    vid_ids = [i["contentDetails"]["videoId"] for i in pl_resp.get("items", [])]
    if not vid_ids:
        return []
    v_resp = yt.videos().list(part="snippet,statistics,status", id=",".join(vid_ids)).execute()
    out = []
    for v in v_resp.get("items", []):
        st = v.get("statistics", {})
        sn = v.get("snippet", {})
        out.append(
            {
                "id": v["id"],
                "url": f"https://www.youtube.com/watch?v={v['id']}",
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "tags": sn.get("tags", []),
                "categoryId": sn.get("categoryId", CHANNELS[channel_key]["default_category_id"]),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "privacy": v.get("status", {}).get("privacyStatus", "private"),
            }
        )
    return out


def update_video_metadata(
    channel_key: str,
    video_id: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str | None = None,
) -> dict:
    yt, _ = get_services(channel_key)
    cur = yt.videos().list(part="snippet", id=video_id).execute()
    items = cur.get("items", [])
    if not items:
        raise RuntimeError(f"Video {video_id} not found")
    snippet = items[0]["snippet"]
    snippet["title"] = title[:100]
    snippet["description"] = description[:5000]
    snippet["tags"] = tags[:30]
    if category_id:
        snippet["categoryId"] = category_id
    resp = yt.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    return {"id": resp["id"], "title": resp["snippet"]["title"]}
