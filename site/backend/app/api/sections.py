import logging
from pathlib import Path

from fastapi import APIRouter, Response

from app.sources import get_source_for_section
from app.sources.json_source import ContentError

logger = logging.getLogger(__name__)


def create_router(content_dir: Path) -> APIRouter:
    """Router factory: the content dir is fixed at app-creation time so tests
    can inject a temp dir (a module-level router re-reading env per request
    would ignore the injection)."""
    router = APIRouter(prefix="/api", tags=["content"])

    def _handle(section: str):
        try:
            source = get_source_for_section(section, content_dir)
            return getattr(source, f"get_{section}")()
        except ContentError as e:
            # Spec: malformed content is logged with filename + validation detail.
            logger.error("content error for %s: %s", section, e)
            return Response(status_code=500, content=str(e), media_type="text/plain")

    @router.get("/about")
    def about():
        return _handle("about")

    @router.get("/projects")
    def projects():
        return _handle("projects")

    @router.get("/writing")
    def writing():
        return _handle("writing")

    @router.get("/contact")
    def contact():
        return _handle("contact")

    return router
