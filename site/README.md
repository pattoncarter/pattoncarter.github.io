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
    # one time only: git clone https://github.com/pattoncarter/pattoncarter.github.io.git && cd pattoncarter.github.io
    git pull && cd site
    cp .env.example .env               # first time only; paste the tunnel token
    docker compose up -d --build
One-time Cloudflare step: dashboard -> Networks -> Tunnels -> your tunnel -> public hostname `cpatto.org` -> service `http://app:8000`. If you change `PORT` in `.env`, update that service target too.

## Editing content
Edit `backend/content/*.json` (about, projects, writing, contact). Changes take effect on the next request — no rebuild, no restart. Keep the shapes valid against `backend/app/models.py`; a malformed file makes only that section's endpoint return 500 and the rest of the site keeps working.
