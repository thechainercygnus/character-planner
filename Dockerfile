# syntax=docker/dockerfile:1
# Character Planner: one image for the API (serving the built frontend) and the worker.
# See docs/deploy.md and ADR 0011.
#
# Runtimes match CI: Node 26 (LTS) builds the frontend, Python 3.14 runs the app, as in
# .python-version. Dependabot skips Node majors and Python minors here: runtime upgrades
# are deliberate changes, made together with CI and the dev setup.

# Images are pinned by digest as well as tag (#52), so a rebuild uses exactly what was
# tested; Dependabot updates the tag and digest together.

# uv as its own stage so Dependabot can update it (it doesn't read COPY --from images).
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM node:26-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS app
# Debian's security fixes, applied at build time: the base image is rebuilt on its own
# schedule, and a fix can be out for days before it is (zlib, CVE-2026-76844 and
# CVE-2026-85091, 2026-11-13). The release scan (#61) fails on fixable ones.
# pip goes: the app runs on uv, and pip's vendored urllib3, msgpack and setuptools carry
# their own vulnerabilities.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first, so code changes don't reinstall them. uv's download cache is a build
# cache mount: it speeds up rebuilds and stays out of the image.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

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
