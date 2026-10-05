import os
from pathlib import Path
from typing import Callable

from app.sources.base import ContentSource
from app.sources.json_source import JsonFileSource

# name -> factory(content_dir) -> ContentSource
_REGISTRY: dict[str, Callable[[Path], ContentSource]] = {
    "json": lambda content_dir: JsonFileSource(content_dir),
}


def register_source(name: str, factory: Callable[[Path], ContentSource]) -> None:
    _REGISTRY[name] = factory


def get_source_for_section(section: str, content_dir: Path | None = None) -> ContentSource:
    """Per-section source selection via <SECTION>_SOURCE env var (default 'json').

    A live source covering only some sections must delegate to JsonFileSource
    for the sections it doesn't cover. `content_dir` is threaded in by the app
    (create_app injection); falls back to the CONTENT_DIR env/default when None."""
    name = os.environ.get(f"{section.upper()}_SOURCE", "json")
    if name not in _REGISTRY:
        raise ValueError(f"unknown content source '{name}' for section '{section}'")
    if content_dir is None:
        from app.config import content_dir as default_content_dir
        content_dir = default_content_dir()
    return _REGISTRY[name](content_dir)
