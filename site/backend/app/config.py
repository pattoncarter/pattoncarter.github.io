import os
from pathlib import Path


def content_dir() -> Path:
    return Path(os.environ.get("CONTENT_DIR", "content"))


def static_dir() -> Path | None:
    raw = os.environ.get("STATIC_DIR")
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def port() -> int:
    return int(os.environ.get("PORT", "8000"))
