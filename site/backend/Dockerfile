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
