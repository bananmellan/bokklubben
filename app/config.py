import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    DEV_MODE = _bool(os.environ.get("DEV_MODE"), False)

    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME") or None
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or None
    SMTP_STARTTLS = _bool(os.environ.get("SMTP_STARTTLS"), False)
    SMTP_FROM = os.environ.get("SMTP_FROM", "bokklubben@localhost")
    SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "10"))

    MAX_AVATAR_BYTES = int(os.environ.get("MAX_AVATAR_BYTES", str(2 * 1024 * 1024)))

    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "8000"))
