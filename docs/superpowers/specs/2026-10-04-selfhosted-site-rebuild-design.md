# Self-Hosted Site Rebuild — Design

Date: 2026-10-04
Status: Approved by user (brainstorming, 2026-10-04)

## Background

The `pattoncarter.github.io` repo currently contains only build artifacts of a React + Vite + Tailwind SPA (minified bundles in `assets/`, no source code). The original source was developed on Replit and is not available in this repo. The site is a personal portfolio with sections for About, Projects, Writing, and Contact; all content is hardcoded in the bundle. Links point to Substack (humanotl.substack.com), GitHub repos, Google Drive (resume), and Unsplash images.

The user wants to:
1. Rebuild the source project in a subfolder of this repo so it can be maintained going forward.
2. Structure all data behind internal API endpoints so live sources (Substack RSS, GitHub API) can be plugged in later without redesign — but ship static content for now.
3. Move off GitHub Pages to a self-hosted web server, as a technical challenge.

## Agreed decisions

| Question | Decision |
|---|---|
| Dynamic scope | None live yet; all data flows through internal API endpoints backed by JSON files, structured so live fetchers can be added per-section later |
| Server stack | Python + FastAPI |
| Hosting | Portable Docker Compose stack (FastAPI app + cloudflared sidecar), runs on VPS or homelab identically |
| Frontend design | Rebuild to match the current site's structure, content, and visual style; iterate against the live site as reference |
| Domain | `cpatto.org` (owned via Cloudflare). User already runs Cloudflare Tunnels for subdomains; apex domain will route through a tunnel public hostname. No Caddy/Let's Encrypt — TLS terminates at Cloudflare's edge |

## Architecture

```
Browser ──HTTPS──▶ Cloudflare edge (TLS)
                      │  (tunnel public hostname: cpatto.org)
                      ▼
              cloudflared container ──outbound connection──▶ Cloudflare
                      │  (compose network, no exposed ports)
                      ▼
              app container (single image)
                ├── FastAPI → /api/about, /api/projects, /api/writing, /api/contact, /api/health
                └── StaticFiles → built React SPA at / (SPA fallback for client routes)
                      │ reads per request
                      ▼
              content/*.json  (volume-mounted read-only from repo checkout)
```

One image, one process serves both API and frontend — no CORS, nothing to keep in sync. cloudflared dials out to Cloudflare like the user's existing subdomain tunnels, so the stack works on a VPS or a CGNAT'd homelab box identically. Moving machines = git pull + `docker compose up -d --build` with the same `.env`.

## Repo layout

New source lives in `site/`; the existing Pages build stays at the repo root untouched as fallback.

```
pattoncarter.github.io/
├── index.html, assets/, 404.html, .nojekyll   # existing Pages site — untouched
└── site/
    ├── docker-compose.yml          # app + cloudflared services
    ├── .env.example                # CLOUDFLARE_TUNNEL_TOKEN, PORT
    ├── .gitignore                  # ignores .env (the live tunnel token must never be committed)
    ├── frontend/                   # React + Vite + TypeScript + Tailwind
    │   └── src/
    │       ├── api/                # typed client for /api/* endpoints + mirrored TS types
    │       ├── components/         # Nav, ProjectCard, PointCloud, section error cards, ...
    │       ├── pages/              # About, Projects, Writing, Contact (+ home/hero)
    │       └── App.tsx             # react-router wiring
    └── backend/
        ├── Dockerfile              # multi-stage: node builds frontend → python image serves both
        ├── app/
        │   ├── main.py             # FastAPI instance, static mount, SPA fallback
        │   ├── api/                # one router per section + health
        │   ├── sources/            # ContentSource protocol, JsonFileSource, source registry
        │   └── models.py           # pydantic content models (the API contract)
        └── content/                # about.json, projects.json, writing.json, contact.json
```

Key decisions:
- **Content JSON files are the single source of truth** for all text/links, extracted from the current bundle (`assets/index-D7rXIsh4.js`) during implementation. Volume-mounted read-only into the container, so content edits need no rebuild and no restart (read-per-request).
- **The `sources/` seam**: every endpoint gets data through a `ContentSource` interface; today `JsonFileSource`, later per-section live sources via env var. Endpoints and frontend never change when the source does.
- **TypeScript** frontend so the API client is typed against the same shapes pydantic validates.

## API & data layer

### Endpoints (all GET, same-origin, no auth)

| Endpoint | Returns |
|---|---|
| `/api/health` | `200 {"status": "ok"}` when the process is up **and** the content directory is readable; `503 {"status": "unavailable"}` otherwise. Does not (and cannot) reflect cloudflared state, which lives in a separate container with no shared interface |
| `/api/about` | tagline, bio paragraphs, core competencies, resume URL, social links (hero content included) |
| `/api/projects` | list of `{title, description, technologies[], links{}, image_url}` |
| `/api/writing` | `WritingContent {intro, posts[], archive_url?}` where each post is `{title, url, date?, excerpt?}` — static Substack data now (intro paragraph + archive link included because the live section has them); RSS source slots in later |
| `/api/contact` | email + social links (GitHub, LinkedIn, Substack); point-cloud animation params stay in the component |

### Data flow

```
React section mounts ──▶ GET /api/<section> ──▶ router ──▶ get_source() [FastAPI dependency]
                                                     │ per-section source selection (env var, default "json")
                                                     ▼
                                          JsonFileSource ──▶ reads content/<section>.json
                                                     │ pydantic validation
                                                     ▼
                                                typed response
```

- **Read-per-request**: files are a few KB; reading + validating on every request means content edits take effect on the next page load with no restart or rebuild.
- **Source seam**:

  ```python
  class ContentSource(Protocol):
      def get_about(self) -> AboutContent: ...
      def get_projects(self) -> list[Project]: ...
      def get_writing(self) -> WritingContent: ...   # {intro, posts[], archive_url?}
      def get_contact(self) -> ContactInfo: ...
  ```

  A registry maps each section to a source class chosen by env var — `ABOUT_SOURCE`, `PROJECTS_SOURCE`, `WRITING_SOURCE`, `CONTACT_SOURCE` (all default `json`; e.g. `WRITING_SOURCE=rss` later). Sections are independent — Writing can go live while Projects still reads JSON. Routers and frontend depend on the protocol only. Since selection is per-section, a live source covering only some sections (e.g. RSS for Writing) delegates to `JsonFileSource` for the sections it doesn't cover.
- **Contract**: pydantic models in `backend/app/models.py`; hand-mirrored TypeScript types in `src/api/types.ts`. No codegen for v1. Optional fields (`date?`, `excerpt?`) are true optionals with `None` defaults — a post without them is valid.

### Frontend rebuild specifics

- Vite + React + TypeScript + Tailwind; dark theme; same fonts (Space Grotesk / Inter / Roboto Mono) and palette as the current site.
- react-router routes: `/`, `/about`, `/projects`, `/writing`, `/contact`. Backend SPA fallback (unknown non-API GET → `index.html`) makes deep-link refreshes work natively — no 404.html redirect shim needed.
- Each section fetches its own endpoint and renders independently with a loading state and a styled per-section error card; one bad endpoint never blanks the page.
- Vite dev server proxies `/api` → `localhost:8000` for local frontend dev.
- **Content extraction**: all copy, links, and image URLs are pulled from the current bundle into the JSON files during implementation — nothing from the live site is lost; it stays up as the visual reference.

**Visual parity acceptance criterion:** every section, text block, link, and image present on the current live site appears on the corresponding route of the rebuilt site (order and styling may be refined iteratively; content must not be missing).

## Deployment

### Image (`backend/Dockerfile`, multi-stage)

- Stage 1: `node:22-alpine` — `npm ci && npm run build` for the frontend. (Node 20 reached EOL in April 2026; all locked deps were verified to run on Node 22.)
- Stage 2: `python:3.12-slim` — pinned backend deps, app code + built `dist/`. Non-root user; Docker healthcheck on `/api/health`.

### Compose stack (`site/docker-compose.yml`)

```yaml
services:
  app:
    build: { context: ., dockerfile: backend/Dockerfile }
    environment: { PORT: "${PORT:-8000}", CONTENT_DIR: /app/content }
    volumes: [ ./backend/content:/app/content:ro ]
    restart: unless-stopped
    # deliberately no ports exposed to the host
  cloudflared:
    image: cloudflare/cloudflared
    command: tunnel run --token ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped
```

- `PORT` comes from `.env` (default 8000). The Cloudflare tunnel target must match it — if you change `PORT`, update the dashboard's service target too.
- No host ports at all — cloudflared reaches the app over the compose network. Same posture on VPS and homelab.
- Token-based (remotely-managed) tunnel = no credential files on disk; portability is "same `.env` on the new machine."
- One-time Cloudflare dashboard step: public hostname `cpatto.org` → tunnel → `http://app:${PORT}` (default `http://app:8000`).

### Deploy procedure (either machine)

```bash
git pull && cd site
cp .env.example .env    # paste tunnel token (first time only)
docker compose up -d --build
```

### Local development

- No Docker/tunnel: `uvicorn app.main:app --reload` + `npm run dev` (Vite proxies `/api` → :8000).
- Full stack without tunnel: `docker compose run --rm -p 8000:8000 app` → http://localhost:8000.

## Error handling

| Failure | Behavior |
|---|---|
| Malformed/missing content JSON | Logged with filename + validation detail; that endpoint returns 500; only that section shows its error card; rest of site works |
| API down entirely | Every section renders its independent error state — no blank page |
| Container crash | `restart: unless-stopped` + healthcheck |
| Future live fetcher fails upstream | Documented contract for future source implementations: live sources must fall back to JSON/cached data when upstream fails. Not built in v1 (the v1 test proves only that a fake non-JSON source can serve any section) |
| Secrets | Only the tunnel token, in gitignored `.env`; nothing sensitive in image or repo |

## Testing

- **Backend — pytest, TDD-style during implementation:**
  - Each endpoint returns validated content from fixture JSON.
  - Malformed/missing JSON → 500 + logged; other endpoints unaffected.
  - SPA fallback: `GET /about` serves `index.html`; unknown `/api/*` → JSON 404.
  - Health endpoint.
  - Source registry: env var selects source; a fake `ContentSource` proves a non-JSON source can serve any section (the test that guarantees future RSS/GitHub sources plug in cleanly).
- **Frontend — no test framework for v1** (YAGNI): `tsc` + `npm run build` passing, plus manual visual diff against the live site.
- **Smoke checklist** (pre- and post-deploy): compose up → curl all endpoints → browse all five routes including hard refresh on a deep link → content matches live site.

## Migration plan

1. Build `site/` in this repo; run locally; iterate until it visually matches `pattoncarter.github.io`.
2. Cloudflare: add `cpatto.org` public hostname → tunnel → `app:8000`.
3. Deploy to the first target machine (VPS or homelab) — same commands either way.
4. Verify `https://cpatto.org` end-to-end. Frontend metadata (`og:url` etc.) becomes `cpatto.org` as part of the rebuild.
5. GitHub Pages stays live as fallback; retire whenever the user is confident (or keep as free backup).

## Out of scope (YAGNI)

CMS/admin UI, auth, database, CI/CD pipeline, analytics, SSR, separate web-server container, CORS config, i18n, frontend unit-test framework.

## Amendment (2026-10-04, user-approved during execution)

Task 6 (content extraction) surfaced a parity gap against the live site: per-project detail pages (`/projects/:id`) with long descriptions, "Project Highlights", "Insights & Learnings", and timelines; education entries carry date ranges; Contact has an intro line. The user chose **full parity**. Changes to this design:

- `Project` gains optional fields: `id`, `long_description`, `highlights: list[str] = []`, `insights`, `timeline`, `category` (all defaulted — backward-compatible with existing content).
- `Education` gains optional `date_range`.
- `ContactInfo` gains optional `intro`.
- New frontend route `/projects/:id` (ProjectDetail page) renders the detail fields; ProjectCard titles link to it. No new backend endpoint — the page fetches `/api/projects` and finds by id. The TS mirror in `src/api/types.ts` gains the same fields.
- All detail content is seeded byte-exact from the production bundle into `content/*.json` (plan Task 6A).
- Parity acceptance criterion extended: every field present on a live project detail page appears on the corresponding `/projects/:id` route.
