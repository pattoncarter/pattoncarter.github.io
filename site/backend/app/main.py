from pathlib import Path

from fastapi import FastAPI, Response
from starlette.responses import FileResponse


def create_app(content_dir: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    from app.config import content_dir as default_content_dir
    from app.config import static_dir as default_static_dir

    if content_dir is None:
        content_dir = default_content_dir()
    if static_dir is None:
        static_dir = default_static_dir()

    app = FastAPI(title="Carter Patton — Site API")

    @app.get("/api/health")
    def health() -> dict:
        # Deliberate simplification of the spec's "content dir readable" probe:
        # the Docker volume mount point always exists, so checking for the one
        # file that must always be present is a faithful proxy.
        if not (content_dir / "about.json").is_file():
            return Response(status_code=503, content='{"status": "unavailable"}',
                            media_type="application/json")
        return {"status": "ok"}

    from app.api.sections import create_router as create_sections_router
    app.include_router(create_sections_router(content_dir))

    if static_dir is not None:
        # NO StaticFiles mount here: a Mount at "/" is a full match for every
        # path and would shadow any route registered after it. Instead the
        # catch-all (registered last, so API routes take precedence) serves
        # real files itself and falls back to the SPA shell.
        resolved_static = static_dir.resolve()
        shell = static_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> Response:
            # Unknown API paths (including bare "/api") get a JSON 404, not the SPA shell.
            if full_path == "api" or full_path.startswith("api/"):
                return Response(status_code=404, content='{"detail": "Not Found"}',
                                media_type="application/json")
            candidate = (static_dir / full_path).resolve()
            # Path-containment check: never serve files outside the static dir.
            # is_relative_to (not a string prefix check — "/app/static2" would
            # pass a startswith against "/app/static").
            if candidate.is_file() and candidate.is_relative_to(resolved_static):
                return FileResponse(candidate)
            # Missing index.html (e.g., empty dist mount before build) must not
            # 500 on every navigation.
            if shell.is_file():
                return Response(content=shell.read_text(encoding="utf-8"),
                                media_type="text/html")
            return Response(status_code=404, content='{"detail": "Not Found"}',
                            media_type="application/json")

    return app


app = create_app()
