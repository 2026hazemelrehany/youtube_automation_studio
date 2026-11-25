import json
from google import genai
from config import CHANNELS, GEMINI_API_KEY


def generate_video_plan(channel_key: str, trends: list[dict], topic_hint: str = "") -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    cfg = CHANNELS[channel_key]
    client = genai.Client(api_key=GEMINI_API_KEY)

    top_trends = [
        {"title": t["title"], "views_per_hour": t["views_per_hour"], "tags": t["tags"]}
        for t in trends[:10]
    ]

    policy_note = (
        "Audience is Kids (COPPA compliant, safe, cheerful, educational/storytelling, no scary themes)."
        if cfg["made_for_kids"]
        else "Audience is Games & Movies fans (original commentary, lore, or news narrative to avoid YouTube Reused Content violations)."
    )

    prompt = f"""
You are a YouTube strategist for an English-speaking audience (US, UK, CA, AU).
Channel: {cfg['label']}
Policy & Style: {policy_note}
Optional user topic: {topic_hint or 'Pick the strongest opportunity from the trends'}

Recent high-velocity English-speaking trends:
{json.dumps(top_trends, indent=2)}

Return a valid JSON object with these exact keys:
- "title": catchy SEO title under 70 chars
- "hook": first 5 seconds spoken hook
- "script": 120-200 word original voiceover script
- "description": SEO YouTube description with natural keywords
- "tags": list of 12 relevant English tags
- "thumbnail_prompt": visual prompt for an eye-catching thumbnail
- "trend_reasoning": 1-2 sentences explaining why this should get views
"""

    for model_name in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text)
        except Exception:
            continue
    raise RuntimeError("All Gemini models are currently busy; try again in a moment.")


def improve_old_video_seo(channel_key: str, video: dict) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    cfg = CHANNELS[channel_key]
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
You are a YouTube SEO & CTR specialist for English-speaking audiences (US, UK, CA, AU).
Channel: {cfg['label']} ({'Made for Kids' if cfg['made_for_kids'] else 'General Audience'})

Current video:
- Title: {video.get('title')}
- Views: {video.get('views')}
- Description: {video.get('description', '')[:500]}
- Tags: {video.get('tags', [])}

Rewrite the metadata to maximize click-through rate and search discovery while staying accurate to the video.
Return ONLY valid JSON with:
- "title": stronger SEO title under 70 chars
- "description": improved English description with natural keywords and 3-5 hashtags
- "tags": list of 15 targeted English tags
- "why_improved": 1-2 sentences explaining what was improved
"""
    for model_name in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text)
        except Exception:
            continue
    raise RuntimeError("All Gemini models are currently busy; try again in a moment.")


def audit_channel_growth(channel_key: str, analytics: dict, videos: list[dict]) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    cfg = CHANNELS[channel_key]
    client = genai.Client(api_key=GEMINI_API_KEY)
    summary_vids = [{"title": v["title"], "views": v["views"], "likes": v["likes"]} for v in videos[:15]]
    prompt = f"""
Analyze this YouTube channel for English-speaking growth & monetization readiness.
Channel: {cfg['label']} ({'Made for Kids' if cfg['made_for_kids'] else 'General Audience'})
28-day analytics: {json.dumps(analytics)}
Recent videos: {json.dumps(summary_vids)}

Return ONLY valid JSON with:
- "top_strength": what is working best right now
- "biggest_bottleneck": main reason views/subs are limited
- "next_5_video_ideas": list of 5 specific high-CTR video ideas tailored to this channel
- "action_plan": list of 3 concrete steps to improve retention and CTR this week
"""
    for model_name in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text)
        except Exception:
            continue
    raise RuntimeError("All Gemini models are currently busy; try again in a moment.")
