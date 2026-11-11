"""FastAPI application.

Run locally with: uv run uvicorn character_planner.app:create_app --factory --reload
(--factory means importing this module never reads .env or touches the database.)
"""

import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.config import Settings, get_settings
from character_planner.curated import GearTargets, load_gear_targets
from character_planner.db import Snapshot, StoredToken, init_db, latest_by_kind, make_engine
from character_planner.summary import build_summary

PENDING_STATE_TTL_SECONDS = 600


class ManualSnapshot(BaseModel):
    kind: str
    payload: Any


# Dependencies live at module level so their Annotated aliases are real type aliases.
# Each app keeps its own engine and settings on app.state (set in create_app), which is
# how tests get an isolated database.


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_targets(request: Request) -> GearTargets:
    settings: Settings = request.app.state.settings
    return load_gear_targets(settings.curated_dir / "gear_targets.yaml")


SessionDep = Annotated[Session, Depends(get_session)]
TargetsDep = Annotated[GearTargets, Depends(get_targets)]


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    http: httpx.Client | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings, engine and mocked HTTP client."""
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)
    pending_states: dict[str, float] = {}  # state -> created_at

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(title="Character Planner", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine

    def current_token(session: Session) -> oauth.Token | None:
        stored = session.get(StoredToken, 1)
        if stored is None:
            return None
        token = oauth.Token(stored.access_token, stored.expires_at, stored.scope)
        return None if token.expired else token

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/auth/login")
    def login() -> RedirectResponse:
        if not settings.has_credentials:
            raise HTTPException(500, "BNET_CLIENT_ID / BNET_CLIENT_SECRET are not set")
        now = time.time()
        for stale in [s for s, t in pending_states.items() if now - t > PENDING_STATE_TTL_SECONDS]:
            del pending_states[stale]
        state = oauth.new_state()
        pending_states[state] = now
        return RedirectResponse(oauth.authorize_url(settings, state))

    @app.get("/auth/callback")
    def callback(request: Request, session: SessionDep) -> RedirectResponse:
        params = request.query_params
        state = params.get("state", "")
        if pending_states.pop(state, None) is None:
            raise HTTPException(400, "Unknown or expired login state")
        code = params.get("code")
        if not code:
            raise HTTPException(400, params.get("error_description") or "No code on callback")
        token = oauth.exchange_code(settings, code, client=http)
        session.merge(StoredToken(id=1, **asdict(token)))
        session.commit()
        return RedirectResponse("/status", status_code=303)

    @app.get("/status")
    def status(session: SessionDep) -> dict[str, Any]:
        stored = session.get(StoredToken, 1)
        latest = latest_by_kind(session)
        return {
            "character": settings.character_slug,
            "namespace": settings.profile_namespace,
            "logged_in": current_token(session) is not None,
            "token_expires_at": stored.expires_at if stored else None,
            "latest_snapshots": {k: s.captured_at.isoformat() for k, s in latest.items()},
        }

    @app.post("/sync")
    def sync(session: SessionDep) -> dict[str, int]:
        """Pull every endpoint and store each response, failures included."""
        token = current_token(session)
        if token is None:
            raise HTTPException(401, "Not logged in or token expired; visit /auth/login")
        with BlizzardClient(settings, token, http=http) as client:
            results = client.all_character_data()
        for result in results:
            session.add(
                Snapshot(source="api", kind=result.kind, status=result.status, payload=result.body)
            )
        session.commit()
        return {result.kind: result.status for result in results}

    @app.post("/snapshots/manual", status_code=201)
    def add_manual(entry: ManualSnapshot, session: SessionDep) -> dict[str, int | None]:
        """Fallback for data the API doesn't return: store it in the same shape."""
        snapshot = Snapshot(source="manual", kind=entry.kind, status=200, payload=entry.payload)
        session.add(snapshot)
        session.commit()
        return {"id": snapshot.id}

    @app.get("/snapshots/latest")
    def latest(session: SessionDep) -> dict[str, Any]:
        return {
            kind: {
                "captured_at": s.captured_at.isoformat(),
                "source": s.source,
                "payload": s.payload,
            }
            for kind, s in latest_by_kind(session).items()
        }

    @app.get("/targets")
    def targets(gear: TargetsDep) -> GearTargets:
        return gear

    @app.get("/summary.md", response_class=PlainTextResponse)
    def summary(session: SessionDep, gear: TargetsDep) -> str:
        name = f"{settings.character_name} {settings.character_surname}"
        return build_summary(name, latest_by_kind(session), gear)

    return app
