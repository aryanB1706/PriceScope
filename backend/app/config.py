import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "pricescope")
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
        os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "2000")
    )
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    SCHEDULER_ENABLED = _env_bool("SCHEDULER_ENABLED", False)
    SCRAPE_INTERVAL_HOURS = float(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    SCHEDULER_LOCK_PATH = os.getenv(
        "SCHEDULER_LOCK_PATH",
        os.path.join(tempfile.gettempdir(), "pricescope-scheduler.lock"),
    )

    # Alert emails. Leave SMTP_HOST empty to disable sending.
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USERNAME", "")
    SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
