# syntax=docker/dockerfile:1
# Character Planner: one image for the API (serving the built frontend) and the worker.
# See docs/deploy.md and ADR 0011.

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src/ src/
RUN uv sync --locked --no-dev --no-editable

COPY data/curated/ data/curated/
COPY --from=frontend /frontend/dist frontend/dist

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin planner \
    && mkdir /data && chown planner /data
USER planner

ENV PATH=/app/.venv/bin:$PATH \
    DATABASE_URL=sqlite:////data/character-planner.db \
    POST_LOGIN_REDIRECT=/
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/healthz', timeout=4).status != 200)"]

CMD ["uvicorn", "character_planner.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
