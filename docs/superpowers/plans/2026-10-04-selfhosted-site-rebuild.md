# Self-Hosted Site Rebuild Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the personal website as a self-hosted FastAPI + React app in `site/`, with all content served through internal API endpoints backed by JSON files, deployable via Docker Compose + Cloudflare Tunnel.

**Architecture:** One Docker image serves both the FastAPI backend (`/api/*`) and the built React SPA (static mount + SPA fallback). Content lives in `backend/content/*.json`, read per-request through a swappable `ContentSource` seam so live Substack/GitHub sources can be added later per-section. A `cloudflared` sidecar container provides HTTPS via the user's existing Cloudflare tunnel setup; no host ports are exposed.

**Tech Stack:** Python 3.12 + FastAPI + pydantic (backend, managed with `uv`), React 19 + TypeScript + Vite + Tailwind CSS v4 (frontend), Docker Compose + cloudflared (deployment). Spec: `docs/superpowers/specs/2026-10-04-selfhosted-site-rebuild-design.md`.

**Working directory note:** All paths below are relative to the repo root (`pattoncarter.github.io/`). The existing GitHub Pages files at the repo root are NEVER modified.

**Git identity note:** This machine has no git identity configured. Every commit command in this plan uses one-shot `-c` flags matching the repo's existing history — do not set global or local git config:
```bash
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "..."
```

**Toolchain on this machine:** Node v26, npm 12, Python 3.14 (system), `uv` at `~/.local/bin/uv`, Docker + Compose v5. The backend pins Python 3.12 via uv (matching the Docker image); local dev uses a uv-managed venv.

**Shell note — two machine-specific hazards for background-process steps:**
1. The shell tooling escapes `!` in delivered commands, so `$!` (last background PID) arrives mangled and `kill $PID` fails. Never use `$!`/`kill $PID`.
2. Each command block is delivered as a single shell invocation whose own cmdline contains the full block text, so `pkill -f <pattern>` matches and kills the executing shell itself (the step then ends with a signal exit even though everything else succeeded).

Required form for host-process cleanup: run the pkill as its **own separate command block** (never in the same block as the line that launches the background process), and **bracket the port digit** in the pattern — e.g. `pkill -f "uvicorn app.main:app --port 801[1]"` — so the pattern's literal text (`801[1]`) cannot match itself. Container cleanup uses a docker name-filter stop instead, which queries the daemon (not the host process table) and is immune to both hazards.

---

## Chunk 1: Backend (FastAPI, TDD)

All backend work happens in `site/backend/`. Tests run with `uv run pytest` from inside `site/backend/`. The app is built via a `create_app()` factory so tests can inject temp content/static dirs without env vars.

**Intentional deviation from the spec's `/api/writing` contract (approved during planning review):** the spec sketch shows `/api/writing` returning a bare list of posts and `get_writing() -> list[Post]`. The live site has an intro paragraph and an archive link on that section, so the plan returns `WritingContent {intro, posts[], archive_url?}` instead. The spec's endpoint table and protocol sketch are updated to match; Chunk 2's mirrored TS types follow this shape.

### Task 1: Backend scaffolding + /api/health

**Files:**
- Create: `site/backend/pyproject.toml`
- Create: `site/backend/app/__init__.py` (empty)
- Create: `site/backend/app/config.py`
- Create: `site/backend/app/main.py`
- Create: `site/backend/tests/__init__.py` (empty)
- Create: `site/backend/tests/conftest.py`
- Create: `site/backend/tests/test_health.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "site-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the venv and install deps**

Run (from `site/backend/`):
```bash
uv venv --python 3.12 && uv sync
```
Expected: venv created at `.venv`, deps resolved. (System Python is 3.14; uv fetches 3.12.)

- [ ] **Step 3: Write the failing health test**

`site/backend/tests/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    """App with a temp content dir (seeded with about.json for the health check)
    and NO static dir (no frontend build in tests)."""
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    app = create_app(content_dir=content_dir, static_dir=None)
    return TestClient(app)
```

`site/backend/tests/test_health.py`:
```python
def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_unavailable_when_content_dir_missing(client, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(content_dir=tmp_path / "does-not-exist", static_dir=None)
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
```

- [ ] **Step 4: Run tests to verify they fail**

Run (from `site/backend/`): `uv run pytest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 5: Implement config.py and main.py**

`site/backend/app/config.py`:
```python
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
```

`site/backend/app/main.py`:
```python
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

    if static_dir is not None:
        # NO StaticFiles mount here: a Mount at "/" is a full match for every
        # path and would shadow any route registered after it. Instead the
        # catch-all (registered last, so API routes take precedence) serves
        # real files itself and falls back to the SPA shell.
        resolved_static = static_dir.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> Response:
            if full_path.startswith("api/"):
                return Response(status_code=404, content='{"detail": "Not Found"}',
                                media_type="application/json")
            candidate = (static_dir / full_path).resolve()
            # Path-containment check: never serve files outside the static dir.
            # is_relative_to (not a string prefix check — "/app/static2" would
            # pass a startswith against "/app/static").
            if candidate.is_file() and candidate.is_relative_to(resolved_static):
                return FileResponse(candidate)
            return Response(content=(static_dir / "index.html").read_text(),
                            media_type="text/html")

    return app


app = create_app()
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `site/backend/`): `uv run pytest -v`
Expected: 2 passed

- [ ] **Step 7: Create site/.gitignore**

`site/.gitignore`:
```
.env
**/__pycache__/
backend/.venv/
backend/.pytest_cache/
frontend/node_modules/
frontend/dist/
```
(`uv.lock` and `requirements.txt` stay tracked — they are the pinned dependency record. `**/__pycache__/` matters because Task 16's `git add -A site/` would otherwise commit Python bytecode created by local pytest/uvicorn runs.)

- [ ] **Step 8: Commit**

```bash
git add site/.gitignore site/backend/pyproject.toml site/backend/uv.lock site/backend/app site/backend/tests
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): scaffold FastAPI app with health endpoint and SPA fallback"
```

### Task 2: Pydantic content models

**Files:**
- Create: `site/backend/app/models.py`
- Test: `site/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

`site/backend/tests/test_models.py`:
```python
import pytest

from app.models import AboutContent, ContactInfo, Post, Project


def test_post_optional_fields_default_to_none():
    p = Post(title="T", url="https://x")
    assert p.date is None and p.excerpt is None


def test_project_links_is_dict():
    pr = Project(title="P", description="d", technologies=["a"], links={"repo": "https://r"})
    assert pr.links["repo"] == "https://r"


def test_about_requires_core_fields():
    a = AboutContent(
        tagline="t", hero="h", mission="m", interests="i", quote="q",
        competencies=["c1"], education=[], resume_url="https://r",
        socials={"github": "https://g"},
    )
    assert a.competencies == ["c1"]


def test_about_missing_required_field_raises():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AboutContent(tagline="t")  # everything else missing


def test_contact_minimal():
    c = ContactInfo(email="e@x.com", socials={})
    assert c.email == "e@x.com"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implement models.py**

`site/backend/app/models.py`:
```python
from pydantic import BaseModel


class Education(BaseModel):
    degree: str
    school: str
    description: str = ""


class AboutContent(BaseModel):
    tagline: str
    hero: str
    mission: str
    interests: str
    quote: str
    competencies: list[str]
    education: list[Education]
    resume_url: str
    socials: dict[str, str]


class Project(BaseModel):
    title: str
    description: str
    technologies: list[str] = []
    links: dict[str, str] = {}
    image_url: str | None = None
    role: str | None = None
    status: str | None = None  # e.g. "IN PROGRESS"


class Post(BaseModel):
    title: str
    url: str
    date: str | None = None
    excerpt: str | None = None


class WritingContent(BaseModel):
    intro: str = ""
    posts: list[Post]
    archive_url: str | None = None


class ContactInfo(BaseModel):
    email: str
    socials: dict[str, str] = {}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add site/backend/app/models.py site/backend/tests/test_models.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): add pydantic content models (API contract)"
```

### Task 3: ContentSource seam — protocol, JsonFileSource, registry

**Files:**
- Create: `site/backend/app/sources/__init__.py`
- Create: `site/backend/app/sources/base.py`
- Create: `site/backend/app/sources/json_source.py`
- Test: `site/backend/tests/test_sources.py`

These are unit tests of the seam itself — no HTTP involved (endpoint tests land in Task 4, where the routes exist).

- [ ] **Step 1: Write the failing tests**

`site/backend/tests/test_sources.py`:
```python
import pytest

from app.sources import get_source_for_section, register_source
from app.sources.json_source import ContentError, JsonFileSource


@pytest.fixture
def content_dir(tmp_path):
    d = tmp_path / "content"
    d.mkdir()
    (d / "writing.json").write_text(
        '{"intro": "hi", "posts": [{"title": "P1", "url": "https://p1"}], '
        '"archive_url": null}'
    )
    return d


def test_json_source_get_writing(content_dir):
    source = JsonFileSource(content_dir)
    writing = source.get_writing()
    assert writing.posts[0].title == "P1"
    assert writing.intro == "hi"


def test_json_source_missing_file_raises(content_dir):
    with pytest.raises(ContentError, match="about"):
        JsonFileSource(content_dir).get_about()


def test_json_source_invalid_json_raises(content_dir):
    (content_dir / "writing.json").write_text("{not json")
    with pytest.raises(ContentError, match="invalid"):
        JsonFileSource(content_dir).get_writing()


def test_json_source_validation_error_raises(content_dir):
    # Parses as JSON but fails the pydantic model -> still a ContentError
    (content_dir / "writing.json").write_text('{"posts": "not-a-list"}')
    with pytest.raises(ContentError, match="invalid"):
        JsonFileSource(content_dir).get_writing()


def test_unknown_source_name_raises(monkeypatch):
    monkeypatch.setenv("WRITING_SOURCE", "nope")
    with pytest.raises(ValueError, match="nope"):
        get_source_for_section("writing")


def test_registered_fake_source_selected(monkeypatch, content_dir):
    from app.models import WritingContent

    class FakeSource:
        def get_writing(self):
            return WritingContent(posts=[])

    register_source("fake", lambda d: FakeSource())
    monkeypatch.setenv("WRITING_SOURCE", "fake")
    assert isinstance(get_source_for_section("writing"), FakeSource)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources'`

- [ ] **Step 3: Implement base.py**

`site/backend/app/sources/base.py`:
```python
from typing import Protocol

from app.models import AboutContent, ContactInfo, Project, WritingContent


class ContentSource(Protocol):
    """One implementation per data backend. Live sources (RSS, GitHub) added
    later must implement this and fall back to JSON/cached data when upstream fails."""

    def get_about(self) -> AboutContent: ...
    def get_projects(self) -> list[Project]: ...
    def get_writing(self) -> WritingContent: ...
    def get_contact(self) -> ContactInfo: ...
```

- [ ] **Step 4: Implement json_source.py**

`site/backend/app/sources/json_source.py`:
```python
import json
from pathlib import Path

from pydantic import ValidationError

from app.models import AboutContent, ContactInfo, Project, WritingContent


class ContentError(Exception):
    """Raised when a content file is missing or invalid."""


class JsonFileSource:
    def __init__(self, content_dir: Path):
        self.content_dir = content_dir

    def _raw(self, name: str):
        path = self.content_dir / f"{name}.json"
        if not path.is_file():
            raise ContentError(f"missing content file: {path}")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise ContentError(f"invalid content file {path}: {e}") from e

    def _load(self, name: str, model):
        path = self.content_dir / f"{name}.json"
        try:
            return model.model_validate(self._raw(name))
        except ValidationError as e:
            # JSON that parses but fails the model contract is a content error,
            # not a 500-with-no-traceback: include filename + validation detail.
            raise ContentError(f"invalid content file {path}: {e}") from e

    def get_about(self) -> AboutContent:
        return self._load("about", AboutContent)

    def get_projects(self) -> list[Project]:
        raw = self._raw("projects")
        try:
            return [Project.model_validate(p) for p in raw]
        except ValidationError as e:
            raise ContentError(f"invalid content file {self.content_dir / 'projects.json'}: {e}") from e

    def get_writing(self) -> WritingContent:
        return self._load("writing", WritingContent)

    def get_contact(self) -> ContactInfo:
        return self._load("contact", ContactInfo)
```

- [ ] **Step 5: Implement sources/__init__.py (registry)**

`site/backend/app/sources/__init__.py`:
```python
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
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: 6 passed. Then `uv run pytest -v` — full suite green (health, models, sources).

- [ ] **Step 7: Commit**

```bash
git add site/backend/app/sources site/backend/tests/test_sources.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): ContentSource seam with JsonFileSource and per-section registry"
```

### Task 4: Section endpoints (/api/about, /api/projects, /api/writing, /api/contact)

**Files:**
- Create: `site/backend/app/api/__init__.py` (empty)
- Create: `site/backend/app/api/sections.py`
- Modify: `site/backend/app/main.py`
- Test: `site/backend/tests/test_sections.py`

- [ ] **Step 1: Write the failing tests**

`site/backend/tests/test_sections.py`:
```python
import json

from app.models import WritingContent, Post
from app.sources import register_source

ABOUT = {
    "tagline": "Architecting Resilient Futures",
    "hero": "Building at the intersection of AI, cybersecurity, and human potential.",
    "mission": "m", "interests": "i", "quote": "q",
    "competencies": ["c1"], "education": [],
    "resume_url": "https://r", "socials": {"github": "https://g"},
}

WRITING = {
    "intro": "hi",
    "posts": [{"title": "P1", "url": "https://p1"}],
    "archive_url": None,
}

PROJECTS = [{
    "title": "PR", "description": "d", "technologies": [], "links": {},
    "image_url": None, "role": None, "status": None,
}]

CONTACT = {"email": "e@x.com", "socials": {}}


def test_about_returns_validated_content(client, tmp_path):
    (tmp_path / "content" / "about.json").write_text(json.dumps(ABOUT))
    resp = client.get("/api/about")
    assert resp.status_code == 200
    assert resp.json()["tagline"] == ABOUT["tagline"]


def test_about_malformed_json_is_500_and_health_still_ok(client, tmp_path):
    (tmp_path / "content" / "about.json").write_text("{not json")
    assert client.get("/api/about").status_code == 500
    assert client.get("/api/health").status_code == 200


def test_writing_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "writing.json").write_text(json.dumps(WRITING))
    resp = client.get("/api/writing")
    assert resp.status_code == 200
    assert resp.json()["posts"][0]["title"] == "P1"


def test_writing_missing_file_is_500(client):
    # conftest seeds only about.json
    assert client.get("/api/writing").status_code == 500


def test_projects_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "projects.json").write_text(json.dumps(PROJECTS))
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "PR"


def test_contact_served_from_json_file(client, tmp_path):
    (tmp_path / "content" / "contact.json").write_text(json.dumps(CONTACT))
    resp = client.get("/api/contact")
    assert resp.status_code == 200
    assert resp.json()["email"] == "e@x.com"


class _FakeSource:
    def get_projects(self): raise NotImplementedError
    def get_contact(self): raise NotImplementedError
    def get_about(self):
        return AboutContent(
            tagline="FAKE", hero="h", mission="m", interests="i", quote="q",
            competencies=[], education=[], resume_url="https://r", socials={},
        )
    def get_writing(self):
        return WritingContent(posts=[Post(title="FAKE", url="https://fake")])


def test_registered_fake_source_serves_any_section(client, monkeypatch):
    register_source("fake", lambda content_dir: _FakeSource())
    monkeypatch.setenv("WRITING_SOURCE", "fake")
    monkeypatch.setenv("ABOUT_SOURCE", "fake")
    assert client.get("/api/writing").json()["posts"][0]["title"] == "FAKE"
    assert client.get("/api/about").json()["tagline"] == "FAKE"
```

(Add `AboutContent` to the test file's import line: `from app.models import AboutContent, WritingContent, Post`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sections.py -v`
Expected: FAIL — 404 for `/api/about`, `/api/writing` (routes not registered)

- [ ] **Step 3: Implement the section routers**

`site/backend/app/api/sections.py`:
```python
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
```

`site/backend/app/main.py` — add inside `create_app()`, immediately after the health route definition (note: `content_dir` is already resolved to a concrete Path at this point):
```python
    from app.api.sections import create_router as create_sections_router
    app.include_router(create_sections_router(content_dir))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_sections.py -v`
Expected: 7 passed. Then `uv run pytest -v` — full suite green (health, models, sources, sections).

- [ ] **Step 5: Commit**

```bash
git add site/backend/app/api site/backend/app/main.py site/backend/tests/test_sections.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): section endpoints with per-section source selection and error handling"
```

### Task 5: SPA fallback + static serving tests (incl. hardening from Task 1 review)

**Files:**
- Test: `site/backend/tests/test_spa_fallback.py`
- Modify: `site/backend/app/main.py` (catch-all: guard missing index.html, JSON 404 for bare `/api`)

Task 1's code quality review found two gaps in the catch-all: (1) an unguarded `index.html` read 500s on every navigation when the static dir exists but is empty (Docker auto-creates missing bind-mount paths), and (2) zero test coverage for the security-critical path-containment logic. This task adds that coverage first, then fixes both gaps.

- [ ] **Step 1: Write the test file (10 tests)**

`site/backend/tests/test_spa_fallback.py`:
```python
import json

from fastapi.testclient import TestClient

from app.main import create_app


def _app_with_static(tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><!-- SPA --></html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "main.js").write_text("console.log(1)")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    return create_app(content_dir=content_dir, static_dir=static_dir)


def _app_with_escape_targets(tmp_path):
    """SPA shell plus secrets outside the static dir that must never be served."""
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<html><!-- SPA --></html>")
    (tmp_path / "outside.txt").write_text("SECRET outside")
    sibling = tmp_path / "static2"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SECRET sibling")
    (static_dir / "link.txt").symlink_to(tmp_path / "outside.txt")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    return create_app(content_dir=content_dir, static_dir=static_dir)


def test_deep_link_serves_spa_shell(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/about")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_unknown_api_path_is_json_404(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_bare_api_path_is_json_404(tmp_path):
    # "/api" (no trailing slash) must not fall through to the SPA shell.
    resp = TestClient(_app_with_static(tmp_path)).get("/api")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_static_file_served(tmp_path):
    resp = TestClient(_app_with_static(tmp_path)).get("/assets/main.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_routes_take_precedence_over_spa_catch_all(tmp_path):
    # Regression: a misplaced catch-all/mount would shadow API routes only
    # when static_dir is present — this test pins the production config.
    app = _app_with_static(tmp_path)
    content_dir = tmp_path / "content"
    (content_dir / "about.json").write_text(json.dumps({
        "tagline": "t", "hero": "h", "mission": "m", "interests": "i",
        "quote": "q", "competencies": [], "education": [],
        "resume_url": "https://r", "socials": {},
    }))
    resp = TestClient(app).get("/api/about")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "SPA" not in resp.text


def test_missing_index_html_returns_json_404(tmp_path):
    # Empty static dir (Docker auto-creates missing bind-mount paths) must not
    # 500 on every navigation.
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "about.json").write_text("{}")
    app = create_app(content_dir=content_dir, static_dir=static_dir)
    resp = TestClient(app).get("/about")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_raw_traversal_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/../../outside.txt")
    assert "SECRET" not in resp.text


def test_encoded_traversal_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/..%2F..%2Foutside.txt")
    assert "SECRET" not in resp.text


def test_prefix_sibling_escape_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/../static2/secret.txt")
    assert "SECRET" not in resp.text


def test_symlink_escape_does_not_leak(tmp_path):
    resp = TestClient(_app_with_escape_targets(tmp_path)).get("/link.txt")
    assert "SECRET" not in resp.text
```

- [ ] **Step 2: Run to verify the two expected failures**

Run: `uv run pytest tests/test_spa_fallback.py -v`
Expected: **8 passed, 2 failed**. The failures are `test_bare_api_path_is_json_404` (currently falls through to the SPA shell → 200) and `test_missing_index_html_returns_json_404` (unguarded read → 500). The four escape-vector tests already pass — Task 1's containment check blocks them; they pin that security property against regressions.

- [ ] **Step 3: Fix the catch-all in main.py**

Replace the `if static_dir is not None:` block in `site/backend/app/main.py` with:

```python
    if static_dir is not None:
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
            if candidate.is_file() and candidate.is_relative_to(resolved_static):
                return FileResponse(candidate)
            # Missing index.html (e.g., empty dist mount before build) must not
            # 500 on every navigation.
            if shell.is_file():
                return Response(content=shell.read_text(encoding="utf-8"),
                                media_type="text/html")
            return Response(status_code=404, content='{"detail": "Not Found"}',
                            media_type="application/json")
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all pass — 10/10 in `test_spa_fallback.py`, plus the existing health/models/source/router tests.

- [ ] **Step 5: Commit**

```bash
git add site/backend/tests/test_spa_fallback.py site/backend/app/main.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "test(backend): SPA fallback coverage; fix missing-index 500 and bare /api 404"
```

> **Post-execution note (2026-10-04):** code review found the raw-traversal test vacuous (httpx normalizes literal `..` client-side) and the two-segment encoded vector mis-geometried. Final state: 9 tests — raw test removed (explanatory comment kept), encoded vectors are single-segment (`/..%2Foutside.txt`, `/..%2Fstatic2%2Fsecret.txt`), all three escape canaries assert status 200 + no leak, and were empirically verified to fail with real leakage if the containment check is removed.

### Task 6: Seed content JSON files (extracted from the live bundle)

**Files:**
- Create: `site/backend/content/about.json`
- Create: `site/backend/content/projects.json`
- Create: `site/backend/content/writing.json`
- Create: `site/backend/content/contact.json`

Content below was extracted from the current production bundle (`assets/index-D7rXIsh4.js`), except `tagline` ("Architecting Resilient Futures"), which comes from `index.html`'s `<title>`/og:title — the live hero renders a terminal motif (`$ ./Carter-Patton`) plus the `hero` text instead. The tagline is kept for the page title/meta (the spec requires the field) but Chunk 2 must NOT render it as visible hero text. **Verification step (Step 5) is mandatory**: open https://pattoncarter.github.io and confirm every string, link, and image matches before committing (spec acceptance criterion: no content may be missing).

- [ ] **Step 1: Write about.json**

`site/backend/content/about.json`:
```json
{
  "tagline": "Architecting Resilient Futures",
  "hero": "Building at the intersection of AI, cybersecurity, and human potential.",
  "mission": "My mission is to empower enterprises from all industries to build secure and efficient solutions. I believe secure technology is a powerful lever for growth, and innovation with security at its core is integral to success.",
  "interests": "My interest in the exploration of nature, sci-fi, and electronic music production informs my creative thinking and appreciation for complex systems. These passions provide another lens through which I explore patterns, innovation, and the art of innovation.",
  "quote": "Technology should be a tool for empowerment, not a replacement for our humanity.",
  "competencies": [
    "AI-Enabled Learning & Research Systems",
    "Applied AI Engineering & LLM Integration",
    "Cloud Security Architecture (AWS, Azure)",
    "Contextual Search & Retrieval-Augmented Generation (RAG)",
    "Cybersecurity Strategy Assessment & Risk Analysis",
    "Decentralized Networking & Resilient Communication Systems",
    "Embedded Systems & IoT Development",
    "Full-Stack Web Application Development",
    "Secure Software Development Lifecycle (SDLC)",
    "Security Architecture for Enterprise AI Applications",
    "Systems Automation & Edge Computing",
    "Technical Due Diligence & Cyber Risk Evaluation (M&A)"
  ],
  "education": [
    {
      "degree": "M.S. in Artificial Intelligence",
      "school": "University of Texas at Austin",
      "description": "Multidisciplinary program focused on machine learning, neural networks, and the ethical, secure deployment of AI systems in real-world environments. Emphasis on robust model architecture, AI system resilience, and cybersecurity in ML pipelines."
    },
    {
      "degree": "B.S. Computer Engineering",
      "school": "Texas A&M University",
      "description": "Undergraduate program blending computer science and electrical engineering. Gained hands-on experience with microcontroller programming, real-time systems, and hardware-software integration, while also building a strong foundation in systems programming, computer architecture, and network protocols."
    }
  ],
  "resume_url": "https://drive.google.com/file/d/11OcH409ToCZbbFgkzY076zRFmfSpHlxK/view",
  "socials": {
    "github": "https://github.com/pattoncarter",
    "linkedin": "https://linkedin.com/in/carterpatton",
    "substack": "https://humanotl.substack.com"
  }
}
```

- [ ] **Step 2: Write projects.json**

`site/backend/content/projects.json`:
```json
[
  {
    "title": "GhidraPT - AI-Assisted Reverse Engineering",
    "description": "Extends Ghidra with ChatGPT-powered code insights, accelerating reverse engineering by offering semantic suggestions and variable renaming.",
    "role": "I developed GhidraPT to streamline my own reverse engineering workflows and contribute to the cybersecurity tooling ecosystem. I designed the integration architecture, implemented the plugin, and tested it against several real-world binaries to fine-tune its relevance and responsiveness.",
    "technologies": ["Python", "Ghidra", "ChatGPT API"],
    "links": {
      "repo": "https://github.com/pattoncarter/GhidraPT"
    },
    "image_url": null,
    "status": null
  },
  {
    "title": "HybridRAG Oncology Research Assistant",
    "description": "An LLM-powered assistant that combines vector search and knowledge graphs to deliver explainable, grounded answers to complex oncology research questions.",
    "role": "Developed a hybrid retrieval system combining vector search and knowledge graphs for enhanced information retrieval. Implemented a knowledge graph architecture to provide traceable and grounded answers. Facilitated complex oncology research queries with improved accuracy and transparency. Open-sourced the project to contribute to the research community.",
    "technologies": ["RAG", "Knowledge Graphs", "LLMs"],
    "links": {
      "repo": "https://github.com/pattoncarter/HybridRAG-Oncology-Research_Assistant",
      "report": "https://github.com/pattoncarter/HybridRAG-Oncology-Research_Assistant/blob/main/HybridRAG-Report.pdf"
    },
    "image_url": null,
    "status": null
  },
  {
    "title": "Modjulo - Personalized AI Learning Platform",
    "description": "A platform integrating LLMs for personalized content generation, feedback, and adaptive study plans. Exploring spaced repetition and retention techniques to reinforce foundational concepts.",
    "role": "I co-lead the product vision and technical direction of Modjulo, contributing to knowledge graph modeling, AI integration strategy, and early architecture prototypes. I also help facilitate team discussions on core user needs, market positioning, and long-term differentiation.",
    "technologies": ["LLMs", "Knowledge Graphs"],
    "links": {
      "site": "https://modjulo.ai"
    },
    "image_url": null,
    "status": null
  },
  {
    "title": "ALFRED - Local AI Assistant (IN PROGRESS)",
    "description": "A fully local, voice-controlled AI assistant that integrates LLMs, home automation, and tool orchestration via MCP.",
    "role": "Building a secure, fully offline voice-based AI system using GGUF LLM inference. Integrated STT, TTS, and Python orchestrator with model context protocol (MCP). Enabled GPU-accelerated inference of Qwen3-30B on local RTX 3090 system. Exposed custom tools via FastAPI for IoT, file I/O, security camera analytics. Designed persistent memory system for RLHF and long-term customization. Built with a modular interface to allow future integrations of other LLM APIs.",
    "technologies": ["GGUF", "MCP", "FastAPI"],
    "links": {},
    "image_url": null,
    "status": "IN PROGRESS"
  },
  {
    "title": "Artificial Sunlight System",
    "description": "A modular IoT lighting system that simulates sunlight cycles and weather to support circadian rhythm health using MQTT and real-time control.",
    "role": "As co-creator, I led the system architecture design, MQTT communication stack implementation, power delivery engineering, and circuit safety. Implemented modular MQTT-connected panels capable of displaying artificial sunrise/sunset cycles and real-time weather animations. Designed scalable power and data protocols for dynamic multi-panel behavior (master, slave, pass-through). Crafted custom enclosures using reflective acrylic and aluminum risers to combine thermal performance with aesthetic design.",
    "technologies": ["MQTT", "IoT", "Hardware"],
    "links": {},
    "image_url": null,
    "status": null
  },
  {
    "title": "TALON - Offgrid Mesh Communication for Search and Rescue",
    "description": "An affordable, reliable LoRa mesh network designed to support search-and-rescue operations in infrastructure-poor environments like national parks.",
    "role": "Designed and built handheld devices, repeaters, and base stations using LoRa radios and custom firmware. Implemented a live-updating React frontend for SAR teams, powered by a Supabase PostgreSQL backend. Field-tested devices in dense forests and elevated terrain to validate real-world performance. Developed a rental-based distribution model for park visitors to ensure accessibility and affordability.",
    "technologies": ["LoRa", "React", "Supabase"],
    "links": {},
    "image_url": null,
    "status": null
  }
]
```

- [ ] **Step 3: Write writing.json**

`site/backend/content/writing.json`:
```json
{
  "intro": "A space for deeper dives into technology, entrepreneurship, venture capital, the future of humanity, and the ideas that drive my work. These writings aim to foster nuanced conversations and encourage new perspectives.",
  "posts": [
    {
      "title": "S:N 0x01 – DeepSeek on the DarkWeb, CVE Wobbles, and AI-Generated Malware",
      "url": "https://humanotl.substack.com/p/sn-0x01-deepseek-on-the-darkweb-cve"
    },
    {
      "title": "S:N 0x02 – More Cyber Budget Cuts, Agentic Guardrails, and \u201cUn-phishable\u201d Logins",
      "url": "https://humanotl.substack.com/p/sn-0x02-more-cyber-budget-cuts-agentic"
    },
    {
      "title": "The Big 3 in AI Are Not Who You Think",
      "url": "https://humanotl.substack.com/p/the-big-3-in-ai-are-not-who-you-think"
    }
  ],
  "archive_url": "https://humanotl.substack.com"
}
```

- [ ] **Step 4: Write contact.json**

`site/backend/content/contact.json`:
```json
{
  "email": "pattoncarter@icloud.com",
  "socials": {
    "github": "https://github.com/pattoncarter",
    "linkedin": "https://linkedin.com/in/carterpatton",
    "substack": "https://humanotl.substack.com"
  }
}
```

- [ ] **Step 5: Verify content against the live site**

Open https://pattoncarter.github.io (all sections) and diff every text block, link, and image URL against the JSON files above. Specifically confirm:
- The hero area: note what the terminal motif shows (Task 11 copies the exact lines directly from the live site); do not treat `tagline` as visible hero text.
- Project images: the current bundle references Unsplash photos — extract them with:
```bash
grep -oE 'https://(plus\.)?unsplash\.com/[^"]+' assets/index-D7rXIsh4.js | sort -u
```
and assign each to the correct project's `image_url` field (initial JSON has all-null `image_url`s — this is real work, not a formality).
- Any text present on the live site but missing from the JSON above. Fix all discrepancies in the JSON files.

- [ ] **Step 6: Verify endpoints serve the real content**

Run (from `site/backend/`):
```bash
uv run uvicorn app.main:app --port 8011 &
sleep 2 && curl -s localhost:8011/api/projects | python3 -m json.tool | head -20
curl -s localhost:8011/api/writing | python3 -m json.tool
```
Expected: valid JSON with the project/post data above.

Then, as a **separate command** (see Shell note in the header — cleanup must not share a block with the launch line, and the bracketed port prevents self-matching):
```bash
pkill -f "uvicorn app.main:app --port 801[1]" || true
```
Expected: exit 0 (`|| true` also normalizes the no-match case). `pkill -f` catches both the uv wrapper and its uvicorn child, which PID capture could miss.

- [ ] **Step 7: Commit**

```bash
git add site/backend/content
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): seed content JSON extracted from current production bundle"
```

### Task 6A: Extend content models for full parity (project detail, education dates, contact intro)

**Files:**
- Modify: `site/backend/app/models.py`
- Modify: `site/backend/tests/test_models.py`
- Modify: `site/backend/content/projects.json`, `site/backend/content/about.json`, `site/backend/content/contact.json`

Context (user-approved amendment): the live site has per-project detail pages (`/projects/:id`) with long descriptions, "Project Highlights", "Insights & Learnings", and a timeline; education entries carry date ranges; Contact has an intro line. None of that is representable in the current models. This task extends the wire contract with optional fields (backward-compatible — every new field has a default) and seeds all detail content byte-exact from the production bundle (`assets/index-D7rXIsh4.js` at repo root, READ-ONLY). The frontend consumes these fields in Task 13A; the TS mirror is already updated in Task 9.

- [ ] **Step 1: Inspect the bundle's detail field shapes**

Run (from repo root):
```bash
python3 - <<'EOF'
import re
src = open("assets/index-D7rXIsh4.js", encoding="utf-8").read()
i = src.find("longDescription")
print(repr(src[i-300:i+2000]))
EOF
```
Expected: a project object with fields like `id`, `title`, `description`, `longDescription`, `highlights` (array of strings), `insights`, `timeline`, `category`. **If the actual shape differs** (e.g. `insights` is an array, or `highlights` items are objects), adapt the model in Step 4 to match the bundle exactly, and report the deviation — do not force the bundle data into a different shape.

- [ ] **Step 2: Write failing tests**

Append to `site/backend/tests/test_models.py`:
```python
def test_project_detail_fields_optional():
    p = Project(title="T", description="D")
    assert p.id is None
    assert p.long_description is None
    assert p.highlights == []
    assert p.insights is None
    assert p.timeline is None
    assert p.category is None


def test_project_detail_fields_populated():
    p = Project.model_validate({
        "id": "ghidrapt", "title": "T", "description": "D",
        "long_description": "Para one.\n\nPara two.",
        "highlights": ["h1", "h2"], "insights": "text",
        "timeline": "Jan 2024 - Jun 2024", "category": "AI",
        "technologies": [], "links": {},
    })
    assert p.id == "ghidrapt"
    assert p.highlights == ["h1", "h2"]


def test_education_date_range_optional():
    e = Education(degree="B.S.", school="S")
    assert e.date_range is None


def test_contact_intro_optional():
    c = ContactInfo(email="a@b.c", socials={})
    assert c.intro is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `site/backend/`): `uv run pytest tests/test_models.py -v`
Expected: the four new tests FAIL (AttributeError), the existing 8 pass.

- [ ] **Step 4: Extend the models**

In `site/backend/app/models.py`:
- `Education`: add `date_range: str | None = None`
- `Project`: add `id: str | None = None`, `long_description: str | None = None`, `highlights: list[str] = []`, `insights: str | None = None`, `timeline: str | None = None`, `category: str | None = None` (keep all existing fields and their order)
- `ContactInfo`: add `intro: str | None = None`
- `AboutContent`, `Post`, `WritingContent`: unchanged

- [ ] **Step 5: Run the full backend suite**

Run (from `site/backend/`): `uv run pytest -v`
Expected: ALL pass.

- [ ] **Step 6: Seed detail content byte-exact from the bundle**

For each of the 6 projects in `content/projects.json`, add from the corresponding bundle project object: `id` (e.g. `"ghidrapt"`), `long_description`, `highlights`, `insights`, `timeline`, `category`. Also fix Modjulo's `description` to the bundle text "An AI-powered lifelong learning platform that uses LLMs and knowledge graphs to adaptively guide learners—currently in early development." (Task 6 deliberately kept plan text here as a disclosed residual — replace it now).

In `content/about.json`: add `date_range` to each education entry from the bundle (e.g. "Jan. 2025 - PRESENT", "Aug. 2020 - May 2024" — verify exact strings and spacing in the bundle before writing).

In `content/contact.json`: add `"intro": "Let's connect. I'm always open to discussing new ideas, collaborations, or intriguing challenges."` (verify byte-exact against the bundle, including apostrophe style; keep the file ASCII-only with `\uXXXX` escapes if that is what the bundle string requires).

- [ ] **Step 7: Endpoint check**

Run (from `site/backend/`):
```bash
uv run uvicorn app.main:app --port 8013 &
sleep 2 && curl -s localhost:8013/api/projects | python3 -c "import json,sys; [print(p['id'], p.get('category'), len(p.get('highlights') or [])) for p in json.load(sys.stdin)]"
curl -s localhost:8013/api/contact | python3 -m json.tool
```
Expected: six lines of `(id, category, highlight-count)` with non-null ids; contact JSON shows the intro string.

Then, as a **separate command** (see Shell note in the header — cleanup must not share a block with the launch line, and the bracketed port prevents self-matching):
```bash
pkill -f "uvicorn app.main:app --port 801[3]" || true
```

- [ ] **Step 8: Commit**

```bash
git add site/backend/app/models.py site/backend/tests/test_models.py site/backend/content
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(backend): extend content models for full parity (project detail, education dates, contact intro)"
```

### Task 7: Full backend test suite green + lockfile export

**Files:**
- Modify: `site/backend/tests/test_models.py` (strengthen assertions)
- Create: `site/backend/tests/test_content_files.py`
- Modify: `site/backend/pyproject.toml` + `site/backend/uv.lock` (declare pydantic — currently only a transitive dep of fastapi, but the app imports it directly)
- Create: `site/backend/requirements.txt` (generated)

Context: Task 6A's code-quality review left three advisories to fold in here, before the lockfile is exported: (1) pydantic v2's default `extra='ignore'` silently drops renamed/removed model fields — the new detail-field tests assert only a subset of the values; (2) nothing validates the real committed content files (the rest of the suite is hermetic via tmp_path); (3) pydantic is imported directly but not declared in pyproject.toml, so it must be an explicit dependency before exporting pinned requirements.

- [ ] **Step 1: Strengthen model tests (close the silent-drop hole)**

In `site/backend/tests/test_models.py`:
- In `test_project_detail_fields_populated`, assert ALL six new fields (currently only `id` and `highlights` are asserted):
```python
    assert p.long_description == "Para one.\n\nPara two."
    assert p.insights == "text"
    assert p.timeline == "Jan 2024 - Jun 2024"
    assert p.category == "AI"
```
- In `test_education_date_range_optional`, add a populated assertion:
```python
    e2 = Education(degree="B.S.", school="S", date_range="2020 - 2024")
    assert e2.date_range == "2020 - 2024"
```
- In `test_contact_intro_optional`, add a populated assertion:
```python
    c2 = ContactInfo(email="a@b.c", socials={}, intro="hi")
    assert c2.intro == "hi"
```

- [ ] **Step 2: Add a guard test for the real content files**

Create `site/backend/tests/test_content_files.py`:
```python
"""Guard: the committed content/*.json must always validate against the models.

The rest of the suite is hermetic (tmp_path fixtures); this points the real
JsonFileSource at the real content dir so a typo'd key or type slip in the
seeded data fails locally instead of surfacing as a logged 500 per request.
"""
from pathlib import Path

from app.sources.json_source import JsonFileSource

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def test_real_content_files_validate():
    source = JsonFileSource(CONTENT_DIR)
    assert source.get_about().education
    projects = source.get_projects()
    # Every project needs an id: the /projects/:id detail route depends on it.
    assert projects and all(p.id for p in projects)
    assert source.get_writing().posts
    assert source.get_contact().email
```

- [ ] **Step 3: Declare pydantic as an explicit dependency**

Run (from `site/backend/`): `uv add "pydantic>=2"`
Expected: `pyproject.toml` gains the pydantic entry; `uv.lock` updates.

- [ ] **Step 4: Run the full suite**

Run (from `site/backend/`): `uv run pytest -v`
Expected: ALL tests pass (health, models, sources, sections, spa_fallback, content_files). If any fail, fix before continuing.

- [ ] **Step 5: Commit test hardening**

```bash
git add site/backend/tests/test_models.py site/backend/tests/test_content_files.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "test(backend): pin all detail-field assertions and guard real content files"
```

- [ ] **Step 6: Export pinned requirements for Docker**

Run (from `site/backend/`):
```bash
uv export --no-dev --no-hashes -o requirements.txt
```
Expected: `requirements.txt` created with pinned versions, including pydantic.

- [ ] **Step 7: Commit dependency + lockfile**

```bash
git add site/backend/pyproject.toml site/backend/uv.lock site/backend/requirements.txt
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "chore(backend): declare pydantic explicitly; export pinned requirements for Docker build"
```

---

## Chunk 2: Frontend (React + Vite + Tailwind v4)

All frontend work happens in `site/frontend/`. Per the spec there is **no frontend test framework** — verification for each task is `npm run build` (runs `tsc --noEmit && vite build`; type errors and bundle errors both fail the build) plus manual checks where noted. Scaffolding is done by writing files directly (not `npm create vite`) so execution is fully non-interactive and deterministic.

Design system (Tailwind v4 CSS-first config): dark theme, fonts Space Grotesk (display) / Inter (body) / Roboto Mono (mono), accent cyan. Colors are defined in `@theme` and referenced as utilities (`bg-bg`, `bg-surface`, `border-border`, `text-muted`, `text-accent`, `font-display`). **Exact palette/spacing is refined against the live site in Task 16** — do not treat the hex values below as final.

### Task 8: Scaffold Vite + React + TS + Tailwind v4

**Files:**
- Create: `site/frontend/package.json`
- Create: `site/frontend/package-lock.json` (generated by Step 7's `npm install`)
- Create: `site/frontend/tsconfig.json`
- Create: `site/frontend/vite.config.ts`
- Create: `site/frontend/index.html`
- Create: `site/frontend/src/main.tsx`
- Create: `site/frontend/src/App.tsx` (placeholder, replaced in Task 10)
- Create: `site/frontend/src/vite-env.d.ts`
- Create: `site/frontend/src/index.css`

- [ ] **Step 1: Write package.json**

`site/frontend/package.json`:
```json
{
  "name": "site-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.6.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.1.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "@vitejs/plugin-react": "^4.5.0",
    "tailwindcss": "^4.1.0",
    "typescript": "~5.8.0",
    "vite": "^6.3.0"
  }
}
```

- [ ] **Step 2: Write tsconfig.json**

`site/frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "useDefineForClassFields": true,
    "noEmit": true
  },
  "include": ["src", "vite.config.ts"]
}
```

- [ ] **Step 3: Write vite.config.ts (Tailwind plugin + dev proxy to the backend)**

`site/frontend/vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
```

- [ ] **Step 4: Write index.html (fonts, meta, og tags pointing at cpatto.org)**

`site/frontend/index.html`:
```html
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Carter Patton | Architecting Resilient Futures</title>
    <meta name="description" content="Carter Patton's personal website showcasing projects, writings, and expertise in AI, cybersecurity, and technology innovation." />
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;600&family=Roboto+Mono:wght@400;500&display=swap" rel="stylesheet">
    <meta property="og:title" content="Carter Patton | Architecting Resilient Futures" />
    <meta property="og:description" content="Building at the intersection of AI, cybersecurity, and human potential to create meaningful solutions that scale." />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="https://cpatto.org" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write src/vite-env.d.ts, src/index.css (Tailwind v4 theme), and src/main.tsx**

`site/frontend/src/vite-env.d.ts` (required — without the vite/client types, `tsc --noEmit` fails on the CSS import in main.tsx with TS2307):
```ts
/// <reference types="vite/client" />
```

`site/frontend/src/index.css`:
```css
@import "tailwindcss";

@theme {
  --font-display: "Space Grotesk", sans-serif;
  --font-body: "Inter", sans-serif;
  --font-mono: "Roboto Mono", monospace;
  --color-bg: #0a0e14;
  --color-surface: #11161f;
  --color-border: #1e2633;
  --color-accent: #22d3ee;
  --color-text: #e5e9f0;
  --color-muted: #8b95a7;
}

body {
  background-color: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
}
```

`site/frontend/src/main.tsx`:
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 6: Write a placeholder App.tsx so the build has an entry**

`site/frontend/src/App.tsx`:
```tsx
export default function App() {
  return <p className="font-mono text-muted">scaffold ok</p>
}
```

- [ ] **Step 7: Install and verify the build**

Run (from `site/frontend/`):
```bash
npm install && npm run build
```
Expected: install succeeds; build outputs `dist/index.html` + `dist/assets/*`. If tsc or vite errors, fix before continuing. A warning that esbuild's postinstall script was blocked is harmless — the build still passes.

- [ ] **Step 8: Commit**

```bash
git add site/frontend/package.json site/frontend/package-lock.json site/frontend/tsconfig.json site/frontend/vite.config.ts site/frontend/index.html site/frontend/src
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): scaffold Vite + React + TS + Tailwind v4 with dev proxy"
```

`package-lock.json` (generated by `npm install` in Step 7) must be committed: the Docker image build runs `npm ci`, which hard-fails without a tracked lockfile.

### Task 9: API client, types, and content hook

**Files:**
- Create: `site/frontend/src/api/types.ts`
- Create: `site/frontend/src/api/client.ts`
- Create: `site/frontend/src/api/useContent.ts`

- [ ] **Step 1: Write types.ts (mirrors backend/app/models.py — keep in sync manually)**

`site/frontend/src/api/types.ts`:
```ts
// NOTE: optionality mirrors the pydantic wire format exactly — fields with
// defaults in backend/app/models.py are ALWAYS present in JSON (required here),
// and nullable fields are always present with a possibly-null value.

export interface Education {
  degree: string
  school: string
  description: string
  date_range: string | null
}

export interface AboutContent {
  tagline: string
  hero: string
  mission: string
  interests: string
  quote: string
  competencies: string[]
  education: Education[]
  resume_url: string
  socials: Record<string, string>
}

export interface Project {
  id: string | null
  title: string
  description: string
  long_description: string | null
  highlights: string[]
  insights: string | null
  timeline: string | null
  category: string | null
  technologies: string[]
  links: Record<string, string>
  image_url: string | null
  role: string | null
  status: string | null
}

export interface Post {
  title: string
  url: string
  date: string | null
  excerpt: string | null
}

export interface WritingContent {
  intro: string
  posts: Post[]
  archive_url: string | null
}

export interface ContactInfo {
  email: string
  intro: string | null
  socials: Record<string, string>
}
```

- [ ] **Step 2: Write client.ts**

`site/frontend/src/api/client.ts`:
```ts
import type { AboutContent, ContactInfo, Project, WritingContent } from './types'

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path} responded ${resp.status}`)
  return (await resp.json()) as T
}

export const api = {
  about: () => fetchJson<AboutContent>('/api/about'),
  projects: () => fetchJson<Project[]>('/api/projects'),
  writing: () => fetchJson<WritingContent>('/api/writing'),
  contact: () => fetchJson<ContactInfo>('/api/contact'),
}
```

- [ ] **Step 3: Write useContent.ts (per-section loading/error state)**

`site/frontend/src/api/useContent.ts`:
```ts
import { useEffect, useState } from 'react'

export function useContent<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let cancelled = false
    loader()
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setError(e) })
    return () => { cancelled = true }
    // loaders in api/client.ts are stable module-level functions
  }, [loader])

  return { data, error }
}
```

- [ ] **Step 4: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS (types compile; unused modules are tree-shaken but still type-checked via tsc include of src)

- [ ] **Step 5: Commit**

```bash
git add site/frontend/src/api
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): typed API client and per-section content hook"
```

### Task 10: App shell — router, Nav, Footer, SectionError

**Files:**
- Modify: `site/frontend/src/App.tsx` (replace placeholder)
- Modify: `site/frontend/src/index.css` (wrap body rule in `@layer base`)
- Modify: `site/frontend/src/api/useContent.ts` (add loading flag)
- Modify: `site/frontend/src/api/client.ts` (include response body in fetch errors)
- Create: `site/frontend/src/components/Nav.tsx`
- Create: `site/frontend/src/components/Footer.tsx`
- Create: `site/frontend/src/components/SectionError.tsx`
- Create: `site/frontend/src/pages/Home.tsx`, `About.tsx`, `Projects.tsx`, `Writing.tsx`, `Contact.tsx` (stubs; real implementations land in Tasks 11-15)

- [ ] **Step 1: Write Nav.tsx**

`site/frontend/src/components/Nav.tsx`:
```tsx
import { NavLink } from 'react-router-dom'

const links = [
  { to: '/about', label: 'About' },
  { to: '/projects', label: 'Projects' },
  { to: '/writing', label: 'Writing' },
  { to: '/contact', label: 'Contact' },
]

export function Nav() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-bg/80 backdrop-blur">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <NavLink to="/" className="font-display text-lg font-bold tracking-wide">
          CARTER
        </NavLink>
        <div className="flex gap-6 text-sm">
          {links.map(l => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `transition-colors ${isActive ? 'text-accent' : 'text-muted hover:text-text'}`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </header>
  )
}
```

- [ ] **Step 2: Write Footer.tsx (decorative only — social links are sourced from the API on the Contact page)**

`site/frontend/src/components/Footer.tsx`:
```tsx
export function Footer() {
  return (
    <footer className="border-t border-border py-6">
      <p className="mx-auto max-w-5xl px-6 font-mono text-xs text-muted">
        © {new Date().getFullYear()} Carter Patton
      </p>
    </footer>
  )
}
```

- [ ] **Step 3: Write SectionError.tsx (per-section failure UI — one bad endpoint never blanks the page)**

`site/frontend/src/components/SectionError.tsx`:
```tsx
export function SectionError({ section, error }: { section: string; error: unknown }) {
  return (
    <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-6 text-sm text-red-300">
      <p className="font-mono">error :: failed to load {section}</p>
      <p className="mt-2 text-muted">{String(error)}</p>
    </div>
  )
}
```

- [ ] **Step 4: Replace App.tsx with the routed shell**

`site/frontend/src/App.tsx`:
```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Nav } from './components/Nav'
import { Footer } from './components/Footer'
import { Home } from './pages/Home'
import { About } from './pages/About'
import { Projects } from './pages/Projects'
import { Writing } from './pages/Writing'
import { Contact } from './pages/Contact'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen flex-col">
        <Nav />
        <div className="flex-1">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/about" element={<About />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/writing" element={<Writing />} />
            <Route path="/contact" element={<Contact />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 5: Write stub pages so the build passes (real implementations land in Tasks 11-15)**

Create each file under `site/frontend/src/pages/`:

`Home.tsx`:
```tsx
export function Home() { return <main className="px-6 py-24 font-mono text-muted">home</main> }
```
`About.tsx`:
```tsx
export function About() { return <main className="px-6 py-16 font-mono text-muted">about</main> }
```
`Projects.tsx`:
```tsx
export function Projects() { return <main className="px-6 py-16 font-mono text-muted">projects</main> }
```
`Writing.tsx`:
```tsx
export function Writing() { return <main className="px-6 py-16 font-mono text-muted">writing</main> }
```
`Contact.tsx`:
```tsx
export function Contact() { return <main className="px-6 py-16 font-mono text-muted">contact</main> }
```

- [ ] **Step 6: Wrap base CSS in @layer base (Tailwind v4 cascade)**

In Tailwind v4, author CSS outside a cascade layer outranks utility classes — the bare `body` rule in `src/index.css` would silently beat any utility later applied to `<body>`/`<html>`. Replace the end of `site/frontend/src/index.css`:
```css
body {
  background-color: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
}
```
with:
```css
@layer base {
  body {
    background-color: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-body);
  }
}
```

- [ ] **Step 7: Finalize API layer for page consumers**

Two small changes to the Task 9 files so every page has an explicit three-state shape and bad-content failures are debuggable from the UI.

Replace `site/frontend/src/api/useContent.ts` with:
```ts
import { useEffect, useState } from 'react'

export function useContent<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    loader()
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(e); setLoading(false) } })
    return () => { cancelled = true }
    // Pass a stable module-level loader (e.g. `api.about` from api/client.ts),
    // never an inline closure — an inline arrow changes identity every render
    // and would refetch on every render.
  }, [loader])

  return { data, error, loading }
}
```

In `site/frontend/src/api/client.ts`, replace the throw line in `fetchJson` with:
```ts
  if (!resp.ok) throw new Error(`${path} responded ${resp.status}: ${(await resp.text()).slice(0, 200)}`)
```
The backend's 500 body carries the content-file validation detail; surfacing it (SectionError renders `String(error)`) makes bad-content debugging visible without a browser console.

Pages in Tasks 11-15 destructure `{ data, error, loading }`. Inline-ternary pages (Home, Contact) use the three-branch form:
`{error ? <SectionError .../> : loading || !data ? <p className="font-mono text-muted">loading…</p> : <>...</>}`;
early-return pages (About, Projects, ProjectDetail, Writing) use `if (error) return <...><SectionError .../></...>` followed by `if (loading || !data) return <...>loading…</...>`.
(`!data` is a TypeScript narrowing guard — when `loading` is false and there is no error, data is non-null.)

- [ ] **Step 8: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add site/frontend/src/App.tsx site/frontend/src/components site/frontend/src/pages site/frontend/src/index.css site/frontend/src/api
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): routed app shell, section error UI, and loading-aware content hook"
```

### Task 11: Home page (hero)

**Files:**
- Modify: `site/frontend/src/pages/Home.tsx` (replace stub)
- Create: `site/frontend/src/components/ParticleField.tsx` (particle background — spec extracted from the production bundle; also reused by Contact in Task 15)
- Create: `site/frontend/src/components/ScrollToTop.tsx`
- Modify: `site/frontend/src/App.tsx` (add ScrollToTop)
- Modify: `site/frontend/src/index.css` (@theme palette fix + blink keyframes)

Bundle-verified hero facts (production bundle `assets/index-D7rXIsh4.js`, section `#home`) — implementers have no browser, so use these instead of inspecting the live site:
- H1 (hardcoded in the bundle, not an API field): `Carter Patton. ` followed by green spans `Innovator,` `Leader,` `Technologist`.
- Directly below the H1: a single mono line `$ ./Carter-Patton` (green) + blinking block cursor — it is NOT a boxed terminal; it is a plain `<p>`.
- Below that: the hero paragraph — this IS the `hero` field from `/api/about` ("Building at the intersection of AI, cybersecurity, and human potential."). Never hardcode it.
- The live hero also has a full-bleed particle-field background (bundle component `Jx`) and a bordered oscilloscope widget (`MR`). The particle field IS rebuilt (Step 2); the oscilloscope is a known v1 gap (see Task 16 note).
- There are NO CTA buttons in the live hero.
- `tagline` is not visible text; it belongs only in title/meta.

- [ ] **Step 1: Fix @theme palette to the live site's theme + add blink animation**

The scaffold's palette was an approximation; the production CSS theme defines `--accent-blue: #0C1281`, `--accent-green: #66FF66`, `--neutral-white: #E8E8E8`, `--neutral-gray: #333333`, `primary-black: #000000`. In the @theme block of `site/frontend/src/index.css`, replace the color token values with:
```css
  --color-bg: #000000;
  --color-surface: #000000;
  --color-border: #333333;
  --color-accent: #66ff66;
  --color-text: #e8e8e8;
  --color-muted: #8b8b8b;
```
(`muted` ≈ neutral-white at 60% on black. Live cards are black with gray borders, so `surface` equals `bg` — borders do the separating.)

Also add to the @theme block (hero terminal cursor blink — production CSS: `animation: blink 1s step-end infinite`, keyframes opacity 1 → 0 at 50%):
```css
  --animate-blink: blink 1s step-end infinite;

  @keyframes blink {
    0%, 100% { opacity: 1 }
    50% { opacity: 0 }
  }
```

- [ ] **Step 2: Write ParticleField.tsx (production bundle's `Jx`, extracted spec)**

`site/frontend/src/components/ParticleField.tsx`:
```tsx
import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  size: number
  speedX: number
  speedY: number
  color: string
  opacity: number
}

// Spec extracted from the production bundle's particle background (Jx):
// min(100, width/10) drifting dots, 20% green / 80% dark blue, faint green
// connection lines under 100px. The live site uses it on both Home and Contact.
export function ParticleField({ className = '' }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      canvas.width = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
    }
    resize()

    const count = Math.min(100, window.innerWidth / 10)
    const particles: Particle[] = Array.from({ length: count }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      size: Math.random() * 2 + 1,
      speedX: (Math.random() - 0.5) * 0.5,
      speedY: (Math.random() - 0.5) * 0.5,
      color: Math.random() > 0.8 ? '#66FF66' : '#0C1281',
      opacity: Math.random() * 0.5 + 0.2,
    }))

    let raf = 0
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (const p of particles) {
        p.x += p.speedX
        p.y += p.speedY
        if (p.x < 0) p.x = canvas.width
        if (p.x > canvas.width) p.x = 0
        if (p.y < 0) p.y = canvas.height
        if (p.y > canvas.height) p.y = 0
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
        ctx.fillStyle = p.color
        ctx.globalAlpha = p.opacity
        ctx.fill()
      }
      ctx.globalAlpha = 0.1
      ctx.strokeStyle = '#66FF66'
      ctx.lineWidth = 0.5
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          if (Math.sqrt(dx * dx + dy * dy) < 100) {
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.stroke()
          }
        }
      }
      raf = requestAnimationFrame(draw)
    }
    draw()

    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      cancelAnimationFrame(raf)
    }
  }, [])

  return <canvas ref={canvasRef} className={className} />
}
```

- [ ] **Step 3: Write ScrollToTop.tsx and wire it into App.tsx**

`site/frontend/src/components/ScrollToTop.tsx`:
```tsx
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export function ScrollToTop() {
  const { pathname } = useLocation()

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return null
}
```

In `site/frontend/src/App.tsx`, import `ScrollToTop` from `./components/ScrollToTop` and render `<ScrollToTop />` as the first child of `<BrowserRouter>` (before the layout div). Without this, client-side navigation preserves the previous page's scroll offset.

- [ ] **Step 4: Implement Home.tsx**

The static hero (H1 + terminal line) always renders; only the API-sourced paragraph (`data.hero`) carries loading/error states. No CTA buttons — the live hero has none.

`site/frontend/src/pages/Home.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ParticleField } from '../components/ParticleField'
import { SectionError } from '../components/SectionError'

export function Home() {
  const { data, error, loading } = useContent(api.about)

  return (
    <main className="relative isolate flex min-h-screen items-center justify-center overflow-hidden py-20">
      <ParticleField className="absolute inset-0 h-full w-full" />
      <div className="relative z-10 mx-auto max-w-4xl px-4 text-center">
        <h1 className="mb-6 font-display text-4xl font-bold leading-tight md:text-6xl">
          Carter Patton.{' '}
          <span className="text-accent">Innovator,</span>{' '}
          <span className="text-accent">Leader,</span>{' '}
          <span className="text-accent">Technologist</span>
        </h1>
        <p className="mb-8 font-mono text-lg text-text/80 md:text-xl">
          <span className="text-accent">$ ./Carter-Patton</span>
          <span aria-hidden className="ml-1 inline-block h-5 w-2 translate-y-0.5 animate-blink bg-accent" />
        </p>
        {error ? (
          <SectionError section="home" error={error} />
        ) : loading || !data ? (
          <p className="font-mono text-muted">loading…</p>
        ) : (
          <div className="mx-auto mb-8 max-w-2xl">
            <p className="text-lg">{data.hero}</p>
          </div>
        )}
      </div>
    </main>
  )
}
```

- [ ] **Step 5: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add site/frontend/src/pages/Home.tsx site/frontend/src/components/ParticleField.tsx site/frontend/src/components/ScrollToTop.tsx site/frontend/src/App.tsx site/frontend/src/index.css
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): home hero with particle field, live-site palette, scroll-to-top"
```

### Task 12: About page

**Files:**
- Modify: `site/frontend/src/pages/About.tsx` (replace stub)

- [ ] **Step 1: Implement About.tsx**

`site/frontend/src/pages/About.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

export function About() {
  const { data, error, loading } = useContent(api.about)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="about" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-12 px-6 py-16">
      <section>
        <h1 className="font-display text-3xl font-bold">About</h1>
        <p className="mt-4 max-w-3xl leading-relaxed">{data.mission}</p>
        <p className="mt-4 max-w-3xl leading-relaxed text-muted">{data.interests}</p>
        <blockquote className="mt-6 border-l-2 border-accent pl-4 font-display italic text-muted">
          “{data.quote}”
        </blockquote>
      </section>

      <section>
        <h2 className="font-display text-xl font-bold">Core Competencies</h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {data.competencies.map(c => (
            <li key={c} className="rounded-md border border-border bg-surface px-4 py-3 text-sm">{c}</li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-display text-xl font-bold">Education</h2>
        <div className="mt-4 flex flex-col gap-4">
          {data.education.map(e => (
            <article key={e.degree} className="rounded-md border border-border bg-surface p-5">
              <h3 className="font-display font-semibold">{e.degree}</h3>
              {e.date_range && <p className="mt-1 font-mono text-xs text-muted">{e.date_range}</p>}
              <p className="text-sm text-muted">{e.school}</p>
              {e.description && <p className="mt-2 text-sm leading-relaxed">{e.description}</p>}
            </article>
          ))}
        </div>
      </section>

      <a
        href={data.resume_url}
        target="_blank"
        rel="noreferrer"
        className="w-fit rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80"
      >
        View Resume
      </a>
    </main>
  )
}
```

- [ ] **Step 2: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add site/frontend/src/pages/About.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): about page with competencies, education, and resume link"
```

### Task 13: Projects page + ProjectCard

**Files:**
- Create: `site/frontend/src/components/ProjectCard.tsx`
- Modify: `site/frontend/src/pages/Projects.tsx` (replace stub)

- [ ] **Step 1: Write ProjectCard.tsx**

`site/frontend/src/components/ProjectCard.tsx`:
```tsx
import { Link } from 'react-router-dom'
import type { Project } from '../api/types'

// Label values match what the live site renders per link type (verified against
// the production bundle's link objects). Same map as the detail page (Task 13A) — keep in sync.
const linkLabels: Record<string, string> = {
  repo: 'GitHub Repository',
  report: 'Report',
  site: 'Coming Soon',
  final_report: 'Final Report',
  final_presentation: 'Final Presentation',
}

export function ProjectCard({ project }: { project: Project }) {
  return (
    <article className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-6">
      {project.image_url && (
        <img src={project.image_url} alt={project.title} className="h-40 w-full rounded-md object-cover" />
      )}
      <div className="flex items-start justify-between gap-3">
        {/* Only the title links (not the whole card) — the link row below contains
            anchors, and wrapping them in a card-level Link would be invalid HTML. */}
        <h3 className="font-display text-lg font-semibold">
          <Link to={project.id ? `/projects/${project.id}` : '/projects'} className="hover:text-accent hover:underline">
            {project.title}
          </Link>
        </h3>
        {project.status && (
          <span className="whitespace-nowrap rounded bg-accent/10 px-2 py-1 font-mono text-xs text-accent">
            {project.status}
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed">{project.description}</p>
      {project.role && <p className="text-sm leading-relaxed text-muted">{project.role}</p>}
      {project.technologies && project.technologies.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {project.technologies.map(t => (
            <li key={t} className="rounded border border-border px-2 py-1 font-mono text-xs text-muted">{t}</li>
          ))}
        </ul>
      )}
      {project.links && Object.keys(project.links).length > 0 && (
        <div className="mt-auto flex gap-4 pt-2 text-sm">
          {Object.entries(project.links).map(([key, url]) => (
            <a key={key} href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {linkLabels[key] ?? key}
            </a>
          ))}
        </div>
      )}
    </article>
  )
}
```

- [ ] **Step 2: Implement Projects.tsx**

`site/frontend/src/pages/Projects.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ProjectCard } from '../components/ProjectCard'
import { SectionError } from '../components/SectionError'

export function Projects() {
  const { data, error, loading } = useContent(api.projects)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="projects" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <h1 className="font-display text-3xl font-bold">Projects</h1>
      <div className="grid gap-6 md:grid-cols-2">
        {data.map(p => <ProjectCard key={p.title} project={p} />)}
      </div>
      <a href="https://github.com/pattoncarter" target="_blank" rel="noreferrer" className="text-sm text-accent hover:underline">
        View More Projects on GitHub →
      </a>
    </main>
  )
}
```

- [ ] **Step 3: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add site/frontend/src/components/ProjectCard.tsx site/frontend/src/pages/Projects.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): projects page with project cards"
```

### Task 13A: Project detail page (/projects/:id)

**Files:**
- Modify: `site/backend/app/models.py`, `site/backend/tests/test_models.py`, `site/backend/tests/test_content_files.py` (Task 7 review hardening)
- Create: `site/frontend/src/pages/ProjectDetail.tsx`
- Modify: `site/frontend/src/App.tsx` (add route + import)

Depends on Task 6A (models carry `id`/`long_description`/`highlights`/`insights`/`timeline`/`category`) and Task 13 (`linkLabels` convention). The live site has a detail page per project; this closes the parity gap the user approved. No new backend endpoint — the page fetches `/api/projects` and finds by id (six projects; YAGNI). Step 1 folds in two Task 7 quality-review advisories that become user-visible once the detail route ships: pydantic's `extra='ignore'` default still silently drops typo'd *optional* keys in content JSON, and nothing guards against duplicate project ids.

- [ ] **Step 1: Harden content models + id guard (Task 7 review advisories)**

In `site/backend/app/models.py`, add a shared base so unknown keys in content JSON become validation errors instead of being silently dropped:
```python
from pydantic import BaseModel, ConfigDict


class ContentModel(BaseModel):
    """Content contract: unknown keys are data errors, not silently ignored."""
    model_config = ConfigDict(extra="forbid")
```
Change all six content models (`Education`, `AboutContent`, `Project`, `Post`, `WritingContent`, `ContactInfo`) to inherit `ContentModel` instead of `BaseModel`. The committed content files were already verified under `extra='forbid'` during review, so the suite should stay green — if it doesn't, a fixture or content file has a stray key; fix the data, not the model.

Add to `site/backend/tests/test_models.py`:
```python
def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        Project.model_validate({"title": "T", "description": "D", "higlights": []})
```

In `site/backend/tests/test_content_files.py`, replace the current id assertion (the comment + `assert projects and all(p.id for p in projects)`) with:
```python
    assert projects, "projects.json is empty"
    # Every project needs a unique id: the /projects/:id detail route depends on it.
    missing = [p.title for p in projects if not p.id]
    assert not missing, f"projects without id: {missing}"
    ids = [p.id for p in projects]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate project ids: {dupes}"
```

Run (from `site/backend/`): `uv run pytest -v` — ALL pass.

Commit:
```bash
git add site/backend/app/models.py site/backend/tests/test_models.py site/backend/tests/test_content_files.py
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "test(backend): forbid unknown content keys; guard project id uniqueness"
```

- [ ] **Step 2: Implement ProjectDetail.tsx**

`site/frontend/src/pages/ProjectDetail.tsx`:
```tsx
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

// Label values match what the live site renders per link type (verified against
// the production bundle's link objects). Same map as ProjectCard (Task 13) — keep in sync.
const linkLabels: Record<string, string> = {
  repo: 'GitHub Repository',
  report: 'Report',
  site: 'Coming Soon',
  final_report: 'Final Report',
  final_presentation: 'Final Presentation',
}

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const { data, error, loading } = useContent(api.projects)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="projects" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  const project = data.find(p => p.id === id)
  if (!project) {
    return (
      <main className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-16">
        <p className="font-mono text-muted">Project not found.</p>
        <Link to="/projects" className="w-fit text-sm text-accent hover:underline">← Back to Projects</Link>
      </main>
    )
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <Link to="/projects" className="w-fit text-sm text-accent hover:underline">← Back to Projects</Link>
      {project.image_url && (
        <img src={project.image_url} alt={project.title} className="h-64 w-full rounded-lg object-cover" />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-3xl font-bold">{project.title}</h1>
        {project.category && (
          <span className="rounded bg-accent/10 px-2 py-1 font-mono text-xs text-accent">{project.category}</span>
        )}
      </div>
      {project.timeline && <p className="font-mono text-sm text-muted">{project.timeline}</p>}
      <p className="max-w-3xl leading-relaxed">{project.description}</p>
      {project.long_description && (
        <div className="flex max-w-3xl flex-col gap-4 leading-relaxed">
          {project.long_description.split('\n\n').map((para, i) => <p key={i}>{para}</p>)}
        </div>
      )}
      {project.role && (
        <section>
          <h2 className="font-display text-xl font-bold">My Role</h2>
          <p className="mt-2 max-w-3xl leading-relaxed">{project.role}</p>
        </section>
      )}
      {project.highlights && project.highlights.length > 0 && (
        <section>
          <h2 className="font-display text-xl font-bold">Project Highlights</h2>
          <ul className="mt-4 flex flex-col gap-3">
            {project.highlights.map(h => (
              <li key={h} className="rounded-md border border-border bg-surface px-4 py-3 text-sm leading-relaxed">{h}</li>
            ))}
          </ul>
        </section>
      )}
      {project.insights && (
        <section>
          <h2 className="font-display text-xl font-bold">Insights &amp; Learnings</h2>
          <p className="mt-2 max-w-3xl leading-relaxed">{project.insights}</p>
        </section>
      )}
      {project.technologies && project.technologies.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {project.technologies.map(t => (
            <li key={t} className="rounded border border-border px-2 py-1 font-mono text-xs text-muted">{t}</li>
          ))}
        </ul>
      )}
      {project.links && Object.keys(project.links).length > 0 && (
        <div className="flex flex-wrap gap-4 text-sm">
          {Object.entries(project.links).map(([key, url]) => (
            <a key={key} href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              {linkLabels[key] ?? key}
            </a>
          ))}
        </div>
      )}
    </main>
  )
}
```

Note: `insights` renders as a single paragraph per the model (`str | None`). If Task 6A's bundle inspection found it holds multiple paragraphs (contains `\n\n`) or is an array, adapt this render to match.

- [ ] **Step 3: Add the route**

In `site/frontend/src/App.tsx`, import `ProjectDetail` from `./pages/ProjectDetail` and add, immediately after the `/projects` route:
```tsx
<Route path="/projects/:id" element={<ProjectDetail />} />
```

- [ ] **Step 4: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add site/frontend/src/pages/ProjectDetail.tsx site/frontend/src/App.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): project detail page with highlights, insights, and timeline"
```

### Task 14: Writing page

**Files:**
- Modify: `site/frontend/src/pages/Writing.tsx` (replace stub)

- [ ] **Step 1: Implement Writing.tsx**

`site/frontend/src/pages/Writing.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

export function Writing() {
  const { data, error, loading } = useContent(api.writing)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="writing" error={error} /></main>
  if (loading || !data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-16">
      <h1 className="font-display text-3xl font-bold">Writing</h1>
      {data.intro && <p className="max-w-3xl leading-relaxed text-muted">{data.intro}</p>}
      <ul className="flex flex-col gap-4">
        {data.posts.map(post => (
          <li key={post.url}>
            <a
              href={post.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-md border border-border bg-surface p-5 transition-colors hover:border-accent"
            >
              <h2 className="font-display font-semibold">{post.title}</h2>
              {post.date && <p className="mt-1 font-mono text-xs text-muted">{post.date}</p>}
              {post.excerpt && <p className="mt-2 text-sm text-muted">{post.excerpt}</p>}
            </a>
          </li>
        ))}
      </ul>
      {data.archive_url && (
        <a href={data.archive_url} target="_blank" rel="noreferrer" className="text-sm text-accent hover:underline">
          View All Posts on Substack →
        </a>
      )}
    </main>
  )
}
```

Note: posts render in array order deliberately — the live site does not sort by date (verified: no post-sort call exists in the production bundle). Do not reorder `content/writing.json` or add a sort during parity work.

- [ ] **Step 2: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add site/frontend/src/pages/Writing.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): writing page with post list and archive link"
```

### Task 15: Contact page (particle background)

**Files:**
- Modify: `site/frontend/src/pages/Contact.tsx` (replace stub)

The live contact section uses the same particle field as Home (bundle component `Jx`) — reuse `ParticleField` from Task 11; do not create a separate PointCloud component.

- [ ] **Step 1: Implement Contact.tsx**

`site/frontend/src/pages/Contact.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { ParticleField } from '../components/ParticleField'
import { SectionError } from '../components/SectionError'

const socialLabels: Record<string, string> = { github: 'GitHub', linkedin: 'LinkedIn', substack: 'Substack' }

export function Contact() {
  const { data, error, loading } = useContent(api.contact)

  return (
    <main className="relative mx-auto flex min-h-[70vh] max-w-5xl flex-col justify-center gap-8 overflow-hidden px-6 py-16">
      <ParticleField className="pointer-events-none absolute inset-0 h-full w-full opacity-60" />
      <div className="relative">
        <h1 className="font-display text-3xl font-bold">Contact</h1>
        {error ? (
          <SectionError section="contact" error={error} />
        ) : loading || !data ? (
          <p className="mt-4 font-mono text-muted">loading…</p>
        ) : (
          <>
            {data.intro && (
              <p className="mt-4 max-w-2xl leading-relaxed text-muted">{data.intro}</p>
            )}
            <div className="mt-6 flex flex-wrap gap-4">
              <a href={`mailto:${data.email}`} className="rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80">
                {data.email}
              </a>
              {Object.entries(data.socials ?? {}).map(([key, url]) => (
                <a key={key} href={url} target="_blank" rel="noreferrer"
                   className="rounded-md border border-border px-6 py-3 font-display font-semibold transition-colors hover:border-accent">
                  {socialLabels[key] ?? key}
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  )
}
```

- [ ] **Step 2: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add site/frontend/src/pages/Contact.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): contact page with particle background"
```

### Task 16: Full-stack visual parity verification

**Files:**
- Modify: any frontend file where the live site differs (palette, terminal lines, layout, copy)
- Modify: `site/backend/content/*.json` if content gaps were found

This task is manual verification against https://pattoncarter.github.io — the spec's acceptance criterion is that every section, text block, link, and image on the current site appears on the corresponding route of the rebuilt site.

- [ ] **Step 1: Run backend + frontend dev servers**

Terminal 1 (from `site/backend/`):
```bash
uv run uvicorn app.main:app --port 8000 --reload
```
Terminal 2 (from `site/frontend/`):
```bash
npm run dev
```
Expected: Vite serves on http://localhost:5173 and proxies `/api` to the backend.

- [ ] **Step 2: Apply bundle-verified parity fixes + run the audit**

The implementer has no browser, so "walking the live site" is done against the production bundle at repo root `assets/index-D7rXIsh4.js` (READ-ONLY — never modify anything outside `site/`). The controller extracted every content region of the live site from that bundle on 2026-10-04. Apply each fix below EXACTLY, then run the audit script at the end of this step; it must report only the two documented exceptions.

**Content fixes (`site/backend/content/`):**
1. `projects.json` — four `role` values are wrong (the Task 6 extraction concatenated highlight bullets instead of taking the bundle's actual role field). Replace with these exact strings:
   - `hybridrag-oncology-assistant`: `I led the development of the HybridRAG Oncology Research Assistant, focusing on integrating hybrid retrieval mechanisms and ensuring the explainability of the AI-generated responses. My responsibilities included designing the system architecture, implementing the knowledge graph, and fine-tuning the language models for optimal performance in the oncology domain.`
   - `alfred-ai-assistant`: `I’m the sole designer and engineer of ALFRED, leading everything from architectural design to CUDA setup, speech integration, tool execution, and future RLHF training strategy.` (the bundle uses a curly apostrophe in "I’m" — keep it)
   - `artificial-sunlight-system`: `As co-creator, I led the system architecture design, MQTT communication stack implementation, power delivery engineering, and circuit safety. I also contributed to aesthetic design, soldering, and final presentation.`
   - `talon-mesh-communication`: `As one of the lead engineers on TALON, I designed and built handheld communication devices, developed the backend integration with Meshtastic protocols, and co-led field validation trials. I also contributed to software engineering for the base station frontend and helped define system deployment strategies for rugged park environments.`
2. `projects.json` — all six `technologies` arrays are subsets of the live lists. Replace each with the full bundle list:
   - `ghidrapt`: `["Ghidra", "Java", "Python", "ChatGPT API", "Reverse Engineering", "Static Analysis", "OpenAI"]`
   - `hybridrag-oncology-assistant`: `["Python", "PyTorch", "Transformers", "FAISS", "Neo4j", "Hugging Face", "Knowledge Graphs", "Retrieval-Augmented Generation"]`
   - `modjulo-ai-learning-platform`: `["LLMs", "Knowledge Graphs", "Spaced Repetition", "Python", "React", "Vector Search", "LangChain", "Neo4j", "NLP"]`
   - `alfred-ai-assistant`: `["llama.cpp", "MCP", "FastAPI", "Whisper.cpp", "Vosk", "Coqui TTS", "Piper", "Docker", "Python", "Ubuntu", "NVIDIA CUDA", "Tailscale", "Conda"]`
   - `artificial-sunlight-system`: `["ESP32", "MQTT", "Mosquitto", "FastLED", "RGBW LED", "Python", "Raspberry Pi", "WiFi", "Python Weather API", "Custom Circuit Design", "3D Printed Hardware"]`
   - `talon-mesh-communication`: `["LoRa", "Meshtastic", "React", "TypeScript", "Supabase", "PostgreSQL", "Heltec V3", "LilyGo T-Beam", "GPS", "Docker", "Mesh Networking", "IoT"]`
3. `writing.json` — reorder `posts` to the live display order (the bundle's array order, which the live site renders unsorted): first `S:N 0x02 – More Cyber Budget Cuts…`, then `S:N 0x01 – DeepSeek on the DarkWeb…`, then `The Big 3 in AI Are Not Who You Think`. Change NO field values — move whole objects only.

**Frontend copy/structure fixes:**
4. `About.tsx` — restructure to match the live section (live headings verified: section "ABOUT ME", subsections "MY MISSION", "EDUCATION", "BEYOND THE CODE", "CORE COMPETENCIES"):
   - H1 becomes `About Me`.
   - Section heading `My Mission`: render the mission as one `<p>` per `\n\n` paragraph (fixes the Task 12 collapse finding: `{data.mission.split('\n\n').map((p, i) => <p key={i} className="mt-4 max-w-3xl leading-relaxed">{p}</p>)}`), followed by the resume button whose label becomes `View Résumé` (live uses the cedilla; ours currently says "View Resume").
   - Section heading `Education`: content unchanged.
   - New section heading `Beyond the Code`: the interests paragraph moves here (out of the first section).
   - Section heading `Core Competencies`: grid unchanged.
   - Quote block: add a hardcoded terminal line directly above it, matching the live site: `<p className="font-mono text-sm text-accent">$ cat philosophy.txt</p>`.
5. `ProjectDetail.tsx` — reorder to match the live detail page: move the `Project Highlights` section BEFORE the `My Role` section (live order: description, long description, highlights, role, insights).
6. `Writing.tsx` — format dates exactly like the live site's renderer: `new Date(post.date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' }).replace(/\//g, '.')` (renders e.g. `05.06.2025` instead of raw ISO).
7. `Contact.tsx` — replace `socialLabels` with the live card labels: `{ github: '@pattoncarter', linkedin: 'Connect professionally', substack: 'Subscribe to my articles' }`.
8. `Nav.tsx` — match the live chrome: logo becomes `C:/P` (the `/` in accent color); five links including HOME, uppercase labels rendered with a terminal prefix in accent color, e.g. `./ABOUT` (live nav items: HOME, ABOUT, PROJECTS, WRITING, CONTACT).
9. `Footer.tsx` — left side becomes `<CARTER> PATTON` (angle brackets in accent color); right side `© {year} All Rights Reserved`.
10. `ProjectCard.tsx` — one-line robustness fix from the Task 13 review: card key `key={p.title}` → `key={p.id ?? p.title}`.

**Second-pass bundle-verified fixes (controller forensics, 2026-10-04 — apply in addition to items 1-10):**
11. Page H1s use the live site's hash-heading pattern: an accent-colored `#` span, a space, then UPPERCASE text (live markup: `<span class="section-heading-hash text-accent-green">#</span> ABOUT ME`). Apply to all four pages — About `# ABOUT ME`, Projects `# PROJECTS`, Writing `# WRITING`, Contact `# CONNECT` (Contact's H1 is "CONNECT", not "Contact"). Example JSX: `<h1 className="font-display text-3xl font-bold"><span className="text-accent">#</span> ABOUT ME</h1>`.
12. About sub-headings are UPPERCASE and accent-colored on the live site (live h3s use `text-xl ... text-accent-green`): `MY MISSION`, `EDUCATION`, `BEYOND THE CODE`, `CORE COMPETENCIES`. Change the four About section headings to uppercase text + accent color (keep existing size/weight).
13. The philosophy quote is wrapped in ASCII straight double quotes on the live site (`"Technology should be..."` — codepoint 0x22, not curly). In About.tsx render `"{data.quote}"` with straight quotes instead of `“{data.quote}”`.
14. Contact page: (a) add an `Email` heading directly above the email button; (b) each social card renders TWO lines — a platform-name heading (`GitHub`, `LinkedIn`, `Substack`) and the existing label below it (`@pattoncarter`, `Connect professionally`, `Subscribe to my articles`). Live markup per card: `<h3>{platform}</h3><span class="text-sm text-neutral-white/70">{username}</span>` inside the card link. Restructure the label map accordingly, e.g. `{ github: { name: 'GitHub', label: '@pattoncarter' }, linkedin: { name: 'LinkedIn', label: 'Connect professionally' }, substack: { name: 'Substack', label: 'Subscribe to my articles' } }`.
15. Remove the trailing ` →` from the Projects footer link ("View More Projects on GitHub") and the Writing archive link ("View All Posts on Substack") — live renders icon + text with no arrow glyph.
16. `projects.json`: the ALFRED role's curly apostrophe is currently a literal U+2019 while every other non-ASCII character in the file is `\uXXXX`-escaped — write it as `\u2019` for uniformity (parsed value unchanged).

**Known v1 gaps (accepted — do NOT attempt):** the hero's bordered oscilloscope widget; mobile swipe navigation + tutorial overlay; the projects section's interactive category filter buttons; the live nav's `$ menu` mobile toggle; the per-post "Read on Substack" CTA link inside writing post cards (our whole card is the link instead); SVG chevron icon on the detail-page back link (we use a `←` character).

**Accepted parity quirk (2026-10-04, quality review):** the writing date expression from item 6 parses date-only ISO strings as UTC midnight and formats in the viewer's local timezone — viewers west of UTC see each post date shifted one day early. The production bundle uses this exact expression (verified 2026-10-04: `new Date(e.date).toLocaleDateString("en-US",{month:"2-digit",day:"2-digit",year:"numeric"}).replace(/\//g,".")`), so the live site exhibits the identical shift; byte-exact parity takes precedence over a timezone fix. If a timezone-correct rendering is ever wanted, use `post.date.split('-').reverse().join('.')` and re-baseline the parity expectation.
**Do NOT "fix" Modjulo's link label:** the production bundle renders `links:[{type:"Coming Soon",url:"https://modjulo.ai"}]` — a live URL labeled "Coming Soon" is verified parity (re-checked 2026-10-04).
**ALFRED placeholder links:** the bundle's ALFRED entry has two placeholder URLs (`github.com/yourusername/alfred`, `your-demo-link.com`) that were intentionally omitted from content in Task 6 — leave them omitted; the audit below documents this as an expected exception.

Then write `/tmp/parity_audit.py` with EXACTLY this content and run it from the repo root:
```python
import json, re, sys
bundle = open('assets/index-D7rXIsh4.js', encoding='utf-8').read()
def norm(s): return re.sub(r'\s+', ' ', s).strip()
nb = norm(bundle)

def extract_obj(anchor):
    i = bundle.find(anchor)
    if i < 0: return None
    start = bundle.rfind('{', 0, i)
    depth = 0; j = start; in_str = False; esc = False
    while j < len(bundle):
        c = bundle[j]
        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return bundle[start:j+1]
        j += 1

def extract_arr(anchor):
    i = bundle.find(anchor)
    if i < 0: return None
    start = bundle.find('[', i)
    depth = 0; j = start; in_str = False; esc = False
    while j < len(bundle):
        c = bundle[j]
        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == '[': depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0: return bundle[start:j+1]
        j += 1

def parse(t):
    t = re.sub(r'([{,])\s*([A-Za-z_]\w*)\s*:', r'\1"\2":', t)
    t = t.replace("\\'", "'")
    return json.loads(t)

fails = []
ps = {p['id']: p for p in json.load(open('site/backend/content/projects.json'))}
mapping = {'title':'title','description':'description','role':'role','longDescription':'long_description',
           'highlights':'highlights','insights':'insights','timeline':'timeline','category':'category',
           'image':'image_url','technologies':'technologies'}
for pid, j in ps.items():
    b = parse(extract_obj(f'id:"{pid}"'))
    for bf, jf in mapping.items():
        if b.get(bf) != j.get(jf):
            fails.append(f'{pid}.{jf}')
    bl = [x['url'] for x in (b.get('links') or [])]
    jl = list((j.get('links') or {}).values())
    if pid == 'alfred-ai-assistant':
        if sorted(jl) != []: fails.append('alfred links should stay omitted')
    elif sorted(bl) != sorted(jl):
        fails.append(f'{pid}.links')

fr = parse(extract_arr('const FR=['))   # posts live in an array, not a single object
w = json.load(open('site/backend/content/writing.json'))
if [p['title'] for p in fr] != [p['title'] for p in w['posts']]:
    fails.append('writing post order')
for f in ('title','summary','date'):
    for bp, jp in zip(fr, w['posts']):
        jf = 'excerpt' if f == 'summary' else f
        if bp.get(f) != jp.get(jf): fails.append(f'writing.{jf}: {jp["title"][:30]}')

for name in ('about.json','contact.json'):
    def walk(o, out):
        if isinstance(o, str):
            for part in o.split('\n\n'):
                if len(part.strip()) > 15: out.append(norm(part))
        elif isinstance(o, dict):
            for v in o.values(): walk(v, out)
        elif isinstance(o, list):
            for v in o: walk(v, out)
    strs = []
    walk(json.load(open('site/backend/content/' + name)), strs)
    for s in strs:
        if s not in nb and 'Architecting Resilient Futures' != s:
            fails.append(f'{name}: {s[:50]}')

if fails:
    print('PARITY AUDIT FAIL:'); [print(' -', f) for f in fails]; sys.exit(1)
print('PARITY AUDIT PASS (only documented exceptions expected and tolerated)')
```
Expected: `PARITY AUDIT PASS`. If it fails, fix the flagged content/copy and re-run until clean.

- [ ] **Step 3: Verify the built frontend served by the real backend (production path)**

Run (from `site/frontend/`): `npm run build`
Then from `site/backend/`:
```bash
STATIC_DIR=../frontend/dist uv run uvicorn app.main:app --port 8012 &
sleep 2
curl -s localhost:8012/api/health
for s in about projects writing contact; do curl -s localhost:8012/api/$s | head -c 100; echo; done
curl -s localhost:8012/about | grep -o 'id="root"'   # SPA shell served for deep link
curl -s "localhost:8012/projects/$(python3 -c "import json;print(json.load(open('content/projects.json'))[0]['id'])")" | grep -o 'id="root"'   # detail-route deep link also serves the shell
curl -s localhost:8012/assets/$(ls ../frontend/dist/assets | grep '\.js$' | head -1) | head -c 80
```
Expected: `{"status":"ok"}`; each of the four section endpoints returns JSON (output starts with `{` or `[` — `/api/projects` is a top-level array), not a plain-text `ContentError` message — this is the check that proves the real `content/*.json` files pass pydantic validation, because the backend test suite uses `tmp_path` fixtures and never reads these files; the `/about` check prints `id="root"` (SPA shell served, not a JSON 404); the JS asset returns JavaScript, not the SPA shell (static file precedence works).

Then, as a **separate command** (see Shell note in the header — cleanup must not share a block with the launch line, and the bracketed port prevents self-matching):
```bash
pkill -f "uvicorn app.main:app --port 801[2]" || true
```
Expected: exit 0. If a re-run fails with "address already in use", a previous uvicorn is still holding the port — run that same pkill command first and retry.

- [ ] **Step 4: Fix all discrepancies found in Steps 2-3**

Apply edits to components/content as needed. Re-run `npm run build` after each batch of frontend changes; re-check the affected route in the browser.

- [ ] **Step 5: Final verification + commit**

Run (from `site/frontend/`): `npm run build` — PASS
Run (from `site/backend/`): `uv run pytest -v` — ALL pass. Note: the suite uses `tmp_path` fixtures, so it does NOT validate the real `content/*.json` files — that is covered by the four section-endpoint curls in Step 3. If you edited content JSON in Step 4, re-run Step 3's endpoint curls to confirm each still returns JSON.

```bash
git add -A site/
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): visual parity with current live site"
```

## Chunk 3: Docker + deployment

Deliverables: a multi-stage image (node builds the frontend → python serves both), the compose stack with a cloudflared sidecar (no host ports), and a containerized smoke test proving the whole path works **without** a tunnel. The one Cloudflare dashboard step (public hostname) is manual user work, documented in `site/README.md` — it cannot be tested from this repo.

### Task 17: docker-compose.yml + .env.example

**Files:**
- Create: `site/docker-compose.yml`
- Create: `site/.env.example`

This task comes before the Dockerfile because the next task builds with `docker compose build app`, which needs the compose file (and `.env` for interpolation) to exist. No host ports on either service — cloudflared reaches the app over the compose network (the spec's VPS/homelab parity requirement). The tunnel token is the only secret; it lives in the gitignored `.env`, never in the image or repo.

- [ ] **Step 1: Write docker-compose.yml**

`site/docker-compose.yml`:
```yaml
services:
  app:
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      PORT: "${PORT:-8000}"
      CONTENT_DIR: /app/content
    volumes:
      - ./backend/content:/app/content:ro
    restart: unless-stopped
    # Deliberately no ports exposed to the host — cloudflared reaches the app
    # over the compose network. Local access uses `docker compose run --rm -p 8000:8000 app`.

  cloudflared:
    image: cloudflare/cloudflared
    command: tunnel run --token ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 2: Write .env.example**

`site/.env.example`:
```
# Cloudflare remote-managed tunnel token (dashboard -> Networks -> Tunnels -> your tunnel).
# Copy this file to .env and paste the real token. .env is gitignored — never commit it.
CLOUDFLARE_TUNNEL_TOKEN=

# Port the app listens on inside the container. If you change this, also update
# the Cloudflare dashboard's service target for cpatto.org (http://app:<PORT>).
PORT=8000
```

- [ ] **Step 3: Verify the compose file parses**

Run (from `site/`):
```bash
cp .env.example .env
docker compose config -q
echo "exit=$?"
```
Expected: no error output and `exit=0`. (`config` only validates YAML + interpolation — the Dockerfile referenced by `build.dockerfile` need not exist yet. An empty token is fine for parsing; the real one gets pasted in at deploy time. `.env` now exists locally but is gitignored.)

- [ ] **Step 4: Commit**

```bash
git add site/docker-compose.yml site/.env.example
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(deploy): compose stack (app + cloudflared, no host ports) and .env.example"
```

### Task 18: Multi-stage Dockerfile + .dockerignore

**Files:**
- Create: `site/backend/Dockerfile`
- Create: `site/.dockerignore`

Build context is `site/` (compose `context: .`), so the Dockerfile addresses both `frontend/` and `backend/`. The image deliberately contains **no** `backend/content/` — content arrives at runtime via the read-only bind mount, so section endpoints returning data in Task 19 proves the volume wiring. `backend/requirements.txt` was exported and committed in Chunk 1 (Task 7); Step 1 verifies it is still in sync with `uv.lock` before the build relies on it.

- [ ] **Step 1: Verify requirements.txt is in sync with the lockfile**

Run (from `site/backend/`):
```bash
uv export --no-dev --no-hashes -o requirements.txt && git diff --exit-code requirements.txt
```
Expected: exit 0, no diff. If a diff appears, dependencies changed without a re-export — inspect it and commit the regenerated file first (`git add site/backend/requirements.txt` + one-shot identity commit `chore(backend): refresh pinned requirements`).

- [ ] **Step 2: Write the Dockerfile**

`site/backend/Dockerfile`:
```dockerfile
# Stage 1: build the frontend (npm ci needs the committed package-lock.json)
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving API + built SPA
FROM python:3.12-slim
ENV PORT=8000 \
    CONTENT_DIR=/app/content \
    STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend-build /build/dist ./static
RUN useradd -u 10001 appuser && mkdir -p /app/content && chown -R appuser: /app
USER appuser
EXPOSE 8000
# python:slim has no curl/wget — probe with the stdlib. Reads $PORT so a
# non-default PORT in .env cannot silently break compose's service_healthy gate.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=2).status==200 else 1)"]
# exec so uvicorn replaces the shell and becomes PID 1 — SIGTERM is then
# delivered directly (graceful shutdown on docker stop / compose down).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

- [ ] **Step 3: Write .dockerignore**

`site/.dockerignore` (keeps the tunnel token and bulky/generated dirs out of the build context):
```
.env
docker-compose.yml
README.md
frontend/node_modules/
frontend/dist/
backend/.venv/
backend/.pytest_cache/
**/__pycache__/
```

- [ ] **Step 4: Build the image**

Run (from `site/`):
```bash
docker compose build app
```
Expected: both stages complete; final image tagged `site-app` (compose's default `<project>-app`). If stage 1 fails with an npm ci lockfile error, `package-lock.json` is missing or stale — re-run Task 8 Step 7 and commit the lockfile.

- [ ] **Step 5: Commit**

```bash
git add site/backend/Dockerfile site/.dockerignore
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(deploy): multi-stage Dockerfile (node build -> python runtime) with healthcheck"
```

### Task 19: Containerized smoke test, site README, final acceptance

**Files:**
- Create: `site/README.md`
- Modify: any file where the smoke test or acceptance check finds a gap

This task proves the production path end-to-end **without** a tunnel: container up → API + SPA served from one process, content from the bind mount. The Cloudflare dashboard step stays manual (documented in the README).

- [ ] **Step 1: Run the app containerized and probe it**

Run (from `site/`):
```bash
docker compose run -d --rm -p 8000:8000 app
sleep 8
curl -s localhost:8000/api/health; echo
for s in about projects writing contact; do curl -s localhost:8000/api/$s | head -c 100; echo; done
curl -s localhost:8000/about | grep -o 'id="root"'
curl -s localhost:8000/assets/$(ls frontend/dist/assets | grep '\.js$' | head -1) | head -c 80
docker ps -q --filter name=site | xargs -r docker stop
```
Expected: `{"status":"ok"}`; each section endpoint returns JSON (starts with `{` or `[` — `/api/projects` is a top-level array); the `/about` check prints `id="root"`; the JS asset returns JavaScript. Because the image contains no `content/` directory, data from the section endpoints can only come from the `:ro` bind mount — this run proves the volume wiring. The final line stops (and via `--rm`, removes) the one-off container. If curl gets connection-refused after the sleep, read the container log: `docker logs $(docker ps -q --filter name=site | head -1)` — but if the container crashed at startup, `--rm` has already removed it and this finds nothing; re-run `docker compose run --rm -p 8000:8000 app` in the foreground to surface the crash directly. If a re-run hits "address already in use", a leftover container is still bound to 8000 — run the filter-stop line first and retry. (Detached run + docker filter-stop rather than `$!`/`kill` — see the Shell note in the header.)

- [ ] **Step 2: Write site/README.md**

`site/README.md`:
````markdown
# cpatto.org — self-hosted site

FastAPI + React personal site. One image serves the API (`/api/*`) and the built SPA; content lives in `backend/content/*.json` and is read per request, so editing content needs no rebuild or restart. Deployed behind a Cloudflare Tunnel (TLS at the edge) — no host ports are exposed, so the same stack runs on a VPS or a CGNAT'd homelab box.

## Layout
- `frontend/` — React 19 + Vite + TypeScript + Tailwind v4 SPA
- `backend/` — FastAPI app (`app/`), pydantic models, content JSON (`content/`), tests
- `docker-compose.yml` — app + cloudflared sidecar
- `.env.example` — copy to `.env` (gitignored) and fill in the tunnel token

## Local development (no Docker)
Terminal 1 (API, from `backend/`):
    uv venv --python 3.12 && uv sync   # first time only
    uv run uvicorn app.main:app --port 8000 --reload
Terminal 2 (SPA, from `frontend/`):
    npm install                        # first time only
    npm run dev                        # http://localhost:5173, proxies /api to :8000

## Full stack without a tunnel
    cp .env.example .env               # first time only
    docker compose build app
    docker compose run --rm -p 8000:8000 app
    # -> http://localhost:8000 (API + SPA from one container)

## Deploy (VPS or homelab — same commands)
    git pull && cd site
    cp .env.example .env               # first time only; paste the tunnel token
    docker compose up -d --build
One-time Cloudflare step: dashboard -> Networks -> Tunnels -> your tunnel -> public hostname `cpatto.org` -> service `http://app:8000`. If you change `PORT` in `.env`, update that service target too.

## Editing content
Edit `backend/content/*.json` (about, projects, writing, contact). Changes take effect on the next request — no rebuild, no restart. Keep the shapes valid against `backend/app/models.py`; a malformed file makes only that section's endpoint return 500 and the rest of the site keeps working.
````

- [ ] **Step 3: Deployment hardening (from the Task 17 quality review)**

1. Pin the cloudflared image so deploys are reproducible from git: pull the current release and pin its exact tag —
   ```bash
   docker pull cloudflare/cloudflared
   docker run --rm cloudflare/cloudflared:latest --version   # -> "cloudflared version <X.Y.Z>"
   ```
   then set `image: cloudflare/cloudflared:<X.Y.Z>` in `site/docker-compose.yml` (replace the bare `cloudflare/cloudflared`). Verify the tag exists in the registry (e.g. it resolves to the same digest as `latest`). Re-run `docker compose config -q` to confirm it still parses. (The originally planned `docker inspect --format '{{.Config.Image}}'` fails on Docker 29.x — "map has no entry for key Image" — hence `--version`.)
2. Fix the stale local-access comment in `site/docker-compose.yml`: the recipe hardcodes `-p 8000:8000` — append "(adjust the host port if you change PORT)" to that comment line.

- [ ] **Step 4: Final acceptance against the spec**

Verify each item (spec "Testing" + "Migration plan"):
1. Backend tests: from `site/backend/`, `uv run pytest -v` — all pass.
2. Frontend build: from `site/frontend/`, `npm run build` — PASS.
3. Containerized app (Step 1's commands): all five routes load in a browser at http://localhost:8000 — `/`, `/about`, `/projects`, `/writing`, `/contact` — including a hard refresh on a deep link (SPA fallback). Content matches the live site (verified against https://pattoncarter.github.io in Task 16).
4. Repo hygiene: `git status --porcelain` shows nothing untracked under `site/` except ignored entries — no `__pycache__`, `node_modules`, `dist`, or `.env` leaked into the index.

- [ ] **Step 5: Commit**

```bash
git add site/README.md site/docker-compose.yml   # plus any files fixed in Steps 1-4, if applicable
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "docs(site): README with local dev, no-tunnel run, and deploy instructions; pin cloudflared image"
```
