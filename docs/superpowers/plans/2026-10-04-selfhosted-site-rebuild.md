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

### Task 7: Full backend test suite green + lockfile export

**Files:**
- Create: `site/backend/requirements.txt` (generated)

- [ ] **Step 1: Run the full suite**

Run (from `site/backend/`): `uv run pytest -v`
Expected: ALL tests pass (health, models, sources, sections, spa_fallback). If any fail, fix before continuing.

- [ ] **Step 2: Export pinned requirements for Docker**

Run (from `site/backend/`):
```bash
uv export --no-dev --no-hashes -o requirements.txt
```
Expected: `requirements.txt` created with pinned versions.

- [ ] **Step 3: Commit**

```bash
git add site/backend/requirements.txt
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "chore(backend): export pinned requirements for Docker build"
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
  title: string
  description: string
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

- [ ] **Step 6: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add site/frontend/src/App.tsx site/frontend/src/components site/frontend/src/pages
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): routed app shell with nav, footer, and section error UI"
```

### Task 11: Home page (hero)

**Files:**
- Modify: `site/frontend/src/pages/Home.tsx` (replace stub)

- [ ] **Step 1: Implement Home.tsx**

The hero text comes from `/api/about` (`hero` field) — never hardcode it. The live site's hero renders a terminal block (per the current production bundle: just a `$ ./Carter-Patton` prompt with a blinking cursor — likely a single line, not a multi-line output). **Before writing the file, open https://pattoncarter.github.io in a browser and copy the EXACT terminal lines** into `TERMINAL_LINES` — do not ship the placeholder values below. (`tagline` is NOT visible text on the live site; it belongs only in title/meta.)

`site/frontend/src/pages/Home.tsx`:
```tsx
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { SectionError } from '../components/SectionError'

// PLACEHOLDER — replace with the exact lines copied from the live site before committing.
const TERMINAL_LINES = ['$ ./Carter-Patton', 'profile: loaded', 'status: building resilient systems']

export function Home() {
  const { data, error } = useContent(api.about)

  return (
    <main className="mx-auto flex max-w-5xl flex-col items-start gap-10 px-6 py-24">
      <div className="w-full max-w-xl rounded-lg border border-border bg-surface p-4 font-mono text-sm">
        {TERMINAL_LINES.map((line, i) => (
          <p key={i} className={i === 0 ? 'text-accent' : 'text-muted'}>{line}</p>
        ))}
      </div>

      {error ? (
        <SectionError section="home" error={error} />
      ) : data ? (
        <>
          <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl">
            {data.hero}
          </h1>
          <div className="flex flex-wrap gap-4">
            <Link to="/projects" className="rounded-md bg-accent px-6 py-3 font-display font-semibold text-bg transition-opacity hover:opacity-80">
              View Projects
            </Link>
            <Link to="/about" className="rounded-md border border-border px-6 py-3 font-display font-semibold transition-colors hover:border-accent">
              About
            </Link>
          </div>
        </>
      ) : (
        <p className="font-mono text-muted">loading…</p>
      )}
    </main>
  )
}
```

- [ ] **Step 2: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

First verify the placeholder was actually replaced (the live site's lines were copied in Step 1). Run from the repo root:
```bash
grep -q "profile: loaded" site/frontend/src/pages/Home.tsx \
  && echo "STOP: TERMINAL_LINES placeholder not replaced - copy the live site's terminal lines first (Step 1)" \
  || echo "OK: placeholder replaced, safe to commit"
```
Expected: `OK: ...`. If it prints `STOP`, go back and fix `TERMINAL_LINES` before committing. (Do not use a `! grep ...` form here — shell tooling on this machine escapes `!` in commands, which would make the guard fail unconditionally.)

```bash
git add site/frontend/src/pages/Home.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): home page with terminal motif and API-driven hero"
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
  const { data, error } = useContent(api.about)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="about" error={error} /></main>
  if (!data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

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
import type { Project } from '../api/types'

const linkLabels: Record<string, string> = { repo: 'Repository', report: 'Report', site: 'Site' }

export function ProjectCard({ project }: { project: Project }) {
  return (
    <article className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-6">
      {project.image_url && (
        <img src={project.image_url} alt={project.title} className="h-40 w-full rounded-md object-cover" />
      )}
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display text-lg font-semibold">{project.title}</h3>
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
  const { data, error } = useContent(api.projects)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="projects" error={error} /></main>
  if (!data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

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
  const { data, error } = useContent(api.writing)

  if (error) return <main className="mx-auto max-w-5xl px-6 py-16"><SectionError section="writing" error={error} /></main>
  if (!data) return <main className="mx-auto max-w-5xl px-6 py-16 font-mono text-muted">loading…</main>

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

- [ ] **Step 2: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add site/frontend/src/pages/Writing.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): writing page with post list and archive link"
```

### Task 15: Contact page + PointCloud animation

**Files:**
- Create: `site/frontend/src/components/PointCloud.tsx`
- Modify: `site/frontend/src/pages/Contact.tsx` (replace stub)

- [ ] **Step 1: Write PointCloud.tsx (canvas point-field; approximation of the current contact animation — refine against the live site in Task 16)**

`site/frontend/src/components/PointCloud.tsx`:
```tsx
import { useEffect, useRef } from 'react'

interface Point { x: number; y: number; z: number }

export function PointCloud({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    const points: Point[] = Array.from({ length: 300 }, () => ({
      x: Math.random(), y: Math.random(), z: Math.random(),
    }))
    const mouse = { x: 0.5, y: 0.5 }

    const onMove = (e: MouseEvent) => {
      const r = canvas.getBoundingClientRect()
      mouse.x = (e.clientX - r.left) / r.width
      mouse.y = (e.clientY - r.top) / r.height
    }

    const resize = () => {
      canvas.width = canvas.clientWidth
      canvas.height = canvas.clientHeight
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (const p of points) {
        p.x = (p.x + 0.0004 * (0.5 + p.z)) % 1
        const px = p.x * canvas.width + (mouse.x - 0.5) * 30 * p.z
        const py = p.y * canvas.height + (mouse.y - 0.5) * 30 * p.z
        ctx.fillStyle = `rgba(34, 211, 238, ${0.2 + p.z * 0.6})`
        ctx.fillRect(px, py, 1.5, 1.5)
      }
      raf = requestAnimationFrame(draw)
    }

    resize()
    // Listener on window (not the canvas): Contact renders this with
    // pointer-events-none for click-through, so a canvas listener never fires.
    // The handler computes position relative to the canvas rect either way.
    window.addEventListener('mousemove', onMove)
    window.addEventListener('resize', resize)
    draw()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return <canvas ref={ref} className={className} />
}
```

- [ ] **Step 2: Implement Contact.tsx**

`site/frontend/src/pages/Contact.tsx`:
```tsx
import { api } from '../api/client'
import { useContent } from '../api/useContent'
import { PointCloud } from '../components/PointCloud'
import { SectionError } from '../components/SectionError'

const socialLabels: Record<string, string> = { github: 'GitHub', linkedin: 'LinkedIn', substack: 'Substack' }

export function Contact() {
  const { data, error } = useContent(api.contact)

  return (
    <main className="relative mx-auto flex min-h-[70vh] max-w-5xl flex-col justify-center gap-8 overflow-hidden px-6 py-16">
      <PointCloud className="pointer-events-none absolute inset-0 h-full w-full opacity-60" />
      <div className="relative">
        <h1 className="font-display text-3xl font-bold">Contact</h1>
        {error ? (
          <SectionError section="contact" error={error} />
        ) : data ? (
          <>
            <p className="mt-4 max-w-2xl leading-relaxed text-muted">
              Connect professionally or reach out directly.
            </p>
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
        ) : (
          <p className="mt-4 font-mono text-muted">loading…</p>
        )}
      </div>
    </main>
  )
}
```

- [ ] **Step 3: Verify the build**

Run (from `site/frontend/`): `npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add site/frontend/src/components/PointCloud.tsx site/frontend/src/pages/Contact.tsx
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "feat(frontend): contact page with point cloud animation"
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

- [ ] **Step 2: Walk every route and diff against the live site**

Open http://localhost:5173 and https://pattoncarter.github.io side by side. For each of `/`, `/about`, `/projects`, `/writing`, `/contact`:
- Every text block present on the live site appears (copy, order, emphasis).
- Every link points to the same target.
- Every image on the live site is present (assign Unsplash URLs found in Task 6 Step 5 into `content/projects.json` if missing).
- The terminal motif on `/` matches the live site's terminal block (the lines were copied into `TERMINAL_LINES` in `Home.tsx` during Task 11 — fix them there if wrong).
- Note palette/spacing differences and adjust `src/index.css` `@theme` values + component classes to match.

- [ ] **Step 3: Verify the built frontend served by the real backend (production path)**

Run (from `site/frontend/`): `npm run build`
Then from `site/backend/`:
```bash
STATIC_DIR=../frontend/dist uv run uvicorn app.main:app --port 8012 &
sleep 2
curl -s localhost:8012/api/health
for s in about projects writing contact; do curl -s localhost:8012/api/$s | head -c 100; echo; done
curl -s localhost:8012/about | grep -o 'id="root"'   # SPA shell served for deep link
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

Build context is `site/` (compose `context: .`), so the Dockerfile addresses both `frontend/` and `backend/`. The image deliberately contains **no** `backend/content/` — content arrives at runtime via the read-only bind mount, so section endpoints returning data in Task 19 proves the volume wiring. `backend/requirements.txt` was already exported and committed in Chunk 1 (Task 7) — nothing to regenerate here.

- [ ] **Step 1: Write the Dockerfile**

`site/backend/Dockerfile`:
```dockerfile
# Stage 1: build the frontend (npm ci needs the committed package-lock.json)
FROM node:20-alpine AS frontend-build
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
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

- [ ] **Step 2: Write .dockerignore**

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

- [ ] **Step 3: Build the image**

Run (from `site/`):
```bash
docker compose build app
```
Expected: both stages complete; final image tagged `site-app` (compose's default `<project>-app`). If stage 1 fails with an npm ci lockfile error, `package-lock.json` is missing or stale — re-run Task 8 Step 7 and commit the lockfile.

- [ ] **Step 4: Commit**

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

- [ ] **Step 3: Final acceptance against the spec**

Verify each item (spec "Testing" + "Migration plan"):
1. Backend tests: from `site/backend/`, `uv run pytest -v` — all pass.
2. Frontend build: from `site/frontend/`, `npm run build` — PASS.
3. Containerized app (Step 1's commands): all five routes load in a browser at http://localhost:8000 — `/`, `/about`, `/projects`, `/writing`, `/contact` — including a hard refresh on a deep link (SPA fallback). Content matches the live site (verified against https://pattoncarter.github.io in Task 16).
4. Repo hygiene: `git status --porcelain` shows nothing untracked under `site/` except ignored entries — no `__pycache__`, `node_modules`, `dist`, or `.env` leaked into the index.

- [ ] **Step 4: Commit**

```bash
git add site/README.md   # plus any files fixed in Step 3, if applicable
git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "docs(site): README with local dev, no-tunnel run, and deploy instructions"
```
