import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TOKENS_DIR = BASE_DIR / "tokens"
QUEUE_DIR = BASE_DIR / "queue"
UPLOADED_DIR = BASE_DIR / "uploaded"
DB_PATH = BASE_DIR / "studio.db"

for d in (TOKENS_DIR, QUEUE_DIR, UPLOADED_DIR):
    d.mkdir(parents=True, exist_ok=True)

CLIENT_SECRET_FILE = os.getenv("CLIENT_SECRET_FILE", "client_secret.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_PRIVACY = os.getenv("DEFAULT_PRIVACY", "private")
DAILY_POST_HOUR_UTC = int(os.getenv("DAILY_POST_HOUR_UTC", "15"))
DAILY_POST_MINUTE_UTC = int(os.getenv("DAILY_POST_MINUTE_UTC", "0"))

ENGLISH_REGIONS = ["US", "GB", "CA", "AU"]
RELEVANCE_LANGUAGE = "en"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

CHANNELS = {
    "kids": {
        "label": "Kids Channel",
        "made_for_kids": True,
        "default_category_id": "1",  # Film & Animation
        "trend_categories": ["1", "24", "27"],  # Film & Animation, Entertainment, Education
        "default_keywords": ["kids story", "nursery rhymes", "kids animation", "educational cartoon"],
        "token_file": TOKENS_DIR / "kids.json",
        "queue_dir": QUEUE_DIR / "kids",
        "uploaded_dir": UPLOADED_DIR / "kids",
    },
    "games_movies": {
        "label": "Games & Movies Channel",
        "made_for_kids": False,
        "default_category_id": "20",  # Gaming
        "trend_categories": ["20", "1", "24"],  # Gaming, Film & Animation, Entertainment
        "default_keywords": ["game lore explained", "movie breakdown", "upcoming games", "trailer analysis"],
        "token_file": TOKENS_DIR / "games_movies.json",
        "queue_dir": QUEUE_DIR / "games_movies",
        "uploaded_dir": UPLOADED_DIR / "games_movies",
    },
    "hazemahmed1720": {
        "label": "Hazem Ahmed (@hazemahmed1720)",
        "made_for_kids": False,
        "default_category_id": "24",
        "trend_categories": ["24", "22"],
        "default_keywords": ["trending", "shorts", "viral"],
        "token_file": TOKENS_DIR / "hazemahmed1720.json",
        "queue_dir": QUEUE_DIR / "hazemahmed1720",
        "uploaded_dir": UPLOADED_DIR / "hazemahmed1720",
    },
}

for cfg in CHANNELS.values():
    cfg["queue_dir"].mkdir(parents=True, exist_ok=True)
    cfg["uploaded_dir"].mkdir(parents=True, exist_ok=True)

STUDIO_PIN = os.getenv("STUDIO_PIN", "")

