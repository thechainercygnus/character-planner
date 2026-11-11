"""FastAPI application.

Run locally with: uv run uvicorn character_planner.app:create_app --factory --reload
(--factory means importing this module never reads .env or touches the database.)
"""

import logging
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import companion_by_id
from character_planner.config import Settings, get_settings
from character_planner.curated import GearTargets, load_gear_targets
from character_planner.db import (
    Snapshot,
    StoredToken,
    catalog_by_name,
    icons_by_id,
    init_db,
    latest_by_kind,
    make_engine,
)
from character_planner.items import RefreshResult, refresh_item_sources
from character_planner.scoring import (
    Weights,
    WeightsView,
    current_weights,
    load_default_weights,
    reset_weights,
    save_weights,
)
from character_planner.summary import build_summary
from character_planner.views import (
    CharacterView,
    GearPlan,
    character_view,
    gear_plan,
    parse_equipment,
)

PENDING_STATE_TTL_SECONDS = 600

logger = logging.getLogger(__name__)


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


def equipped_item_ids(session: Session) -> list[int]:
    equipment = latest_by_kind(session).get("equipment")
    items = parse_equipment(equipment.payload) if equipment else []
    return [item.item_id for item in items if item.item_id is not None]


def get_default_weights(request: Request) -> Weights:
    settings: Settings = request.app.state.settings
    return load_default_weights(settings.curated_dir / "stat_weights.yaml")


class WeightsUpdate(BaseModel):
    weights: dict[str, Annotated[float, Field(ge=-10, le=10, allow_inf_nan=False)]]


SessionDep = Annotated[Session, Depends(get_session)]
DefaultWeightsDep = Annotated[Weights, Depends(get_default_weights)]
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

    @app.get("/api/healthz")
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
        return RedirectResponse(settings.post_login_redirect, status_code=303)

    @app.get("/api/status")
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

    @app.post("/api/sync")
    def sync(session: SessionDep, gear: TargetsDep) -> dict[str, int]:
        """Pull every endpoint and store each response, failures included.

        Then look up any target items not in the item catalog yet. That step is
        best-effort: a catalog failure never fails the sync.
        """
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
        items = refresh_item_sources(session, settings, gear, equipped_item_ids(session), http=http)
        for error in items.errors:
            logger.warning("Item data refresh after sync: %s", error)
        return {result.kind: result.status for result in results}

    @app.post("/api/items/refresh")
    def refresh_items(session: SessionDep, gear: TargetsDep, force: bool = False) -> RefreshResult:
        """Refresh item data from every source. force=true refetches everything.

        Source failures are reported in `errors` rather than failing the request.
        """
        return refresh_item_sources(
            session, settings, gear, equipped_item_ids(session), force=force, http=http
        )

    @app.post("/api/snapshots/manual", status_code=201)
    def add_manual(entry: ManualSnapshot, session: SessionDep) -> dict[str, int | None]:
        """Fallback for data the API doesn't return: store it in the same shape."""
        snapshot = Snapshot(source="manual", kind=entry.kind, status=200, payload=entry.payload)
        session.add(snapshot)
        session.commit()
        return {"id": snapshot.id}

    @app.get("/api/snapshots/latest")
    def latest(session: SessionDep) -> dict[str, Any]:
        return {
            kind: {
                "captured_at": s.captured_at.isoformat(),
                "source": s.source,
                "payload": s.payload,
            }
            for kind, s in latest_by_kind(session).items()
        }

    @app.get("/api/targets")
    def targets(gear: TargetsDep) -> GearTargets:
        return gear

    @app.get("/api/summary.md", response_class=PlainTextResponse)
    def summary(session: SessionDep, gear: TargetsDep, defaults: DefaultWeightsDep) -> str:
        name = f"{settings.character_name} {settings.character_surname}"
        return build_summary(
            name,
            latest_by_kind(session),
            gear,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, defaults),
        )

    @app.get("/api/character")
    def character(session: SessionDep) -> CharacterView:
        return character_view(latest_by_kind(session), icons_by_id(session))

    @app.get("/api/gear")
    def gear(session: SessionDep, targets: TargetsDep, defaults: DefaultWeightsDep) -> GearPlan:
        return gear_plan(
            latest_by_kind(session),
            targets,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, defaults),
        )

    def weights_view(session: Session, defaults: Weights) -> WeightsView:
        current = current_weights(session, defaults)
        return WeightsView(
            weights=current.weights,
            defaults=defaults.weights,
            customised=current.weights != defaults.weights,
        )

    @app.get("/api/weights")
    def get_weights(session: SessionDep, defaults: DefaultWeightsDep) -> WeightsView:
        """Stat weights used to score gear, and the shipped defaults."""
        return weights_view(session, defaults)

    @app.put("/api/weights")
    def put_weights(
        update: WeightsUpdate, session: SessionDep, defaults: DefaultWeightsDep
    ) -> WeightsView:
        """Replace the weights. Stats left out fall back to their default weight."""
        names = [name.strip() for name in update.weights]
        if any(not name or len(name) > 40 for name in names):
            raise HTTPException(422, "Stat names must be 1-40 characters")
        save_weights(session, {name.strip(): value for name, value in update.weights.items()})
        return weights_view(session, defaults)

    @app.delete("/api/weights")
    def delete_weights(session: SessionDep, defaults: DefaultWeightsDep) -> WeightsView:
        """Go back to the defaults in data/curated/stat_weights.yaml."""
        reset_weights(session)
        return weights_view(session, defaults)

    # Serve the built frontend (npm run build) from the same origin, after every API
    # route so those win. In development Vite serves it instead and proxies to us.
    if (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

    return app
