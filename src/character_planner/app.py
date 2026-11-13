"""FastAPI application.

Run locally with: uv run uvicorn character_planner.app:create_app --factory --reload
(--factory means importing this module never reads .env or touches the database.)
"""

import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, notify
from character_planner.blizzard import oauth
from character_planner.choices import (
    ChoiceKind,
    ItemChoiceView,
    clear_choice,
    list_choices,
    set_choice,
    stored_choices,
)
from character_planner.companion import companion_by_id
from character_planner.config import Settings, get_settings
from character_planner.curated import GearTargets
from character_planner.db import (
    NotificationDestination,
    Snapshot,
    StoredToken,
    catalog_by_name,
    icons_by_id,
    init_db,
    latest_by_kind,
    make_engine,
)
from character_planner.enchants import (
    EnchantAdvice,
    EnchantData,
    EnchantOption,
    RecipeRefresh,
    advise,
    catalog,
    equipped_effects,
    load_enchant_data,
    refresh_enchant_data,
)
from character_planner.guest import (
    Faction,
    GuestError,
    GuestOptions,
    guest_options,
    guest_recommendations,
)
from character_planner.items import RefreshResult, refresh_item_sources
from character_planner.jobs import (
    NotLoggedIn,
    character_context,
    current_token,
    equipped_item_ids,
    gear_targets,
    sync_character,
)
from character_planner.logs import ACCESS_LOGGER, configure_logging, request_id, safe_database_url
from character_planner.pool import (
    PoolRefresh,
    PoolView,
    pool_view,
)
from character_planner.progress import Progress, progress
from character_planner.recommend import Recommendations, UsageRules, load_rules, recommend
from character_planner.rules import (
    EditedRules,
    RulesError,
    RulesView,
    current_rules,
    reset_rules,
    rules_view,
    save_rules,
)
from character_planner.scoring import (
    PresetError,
    ShippedPresets,
    UnknownPreset,
    WeightsView,
    activate,
    create_preset,
    current_weights,
    delete_preset,
    load_shipped_presets,
    migrate_stored_weights,
    rename_preset,
    reset_weights,
    save_weights,
    weights_view,
)
from character_planner.summary import build_summary
from character_planner.talents import (
    TalentPlan,
    TalentPlanView,
    compare,
    current_plan,
    load_default_plan,
    reset_plan,
    save_plan,
)
from character_planner.targets import (
    EditedTargets,
    TargetsError,
    pin_target,
    reset_targets,
    save_targets,
    unpin_target,
)
from character_planner.targets import is_customised as targets_customised
from character_planner.views import (
    CharacterView,
    EquippedItem,
    GearPlan,
    character_level,
    character_view,
    gear_plan,
    known_recipe_ids,
    parse_equipment,
    parse_specialization,
)

PENDING_STATE_TTL_SECONDS = 600

logger = logging.getLogger(__name__)
access_logger = logging.getLogger(ACCESS_LOGGER)
# An incoming X-Request-ID is reused when it looks like an id, so a proxy's id carries.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def app_version() -> str:
    try:
        return version("character-planner")
    except PackageNotFoundError:
        return "(not installed)"


class ManualSnapshot(BaseModel):
    kind: str
    payload: Any


# Dependencies live at module level so their Annotated aliases are real type aliases.
# Each app keeps its own engine and settings on app.state (set in create_app), which is
# how tests get an isolated database.


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_targets(request: Request, session: SessionDep) -> GearTargets:
    """gear_targets.yaml, with item ids filled in from the item pool where it has them."""
    return gear_targets(session, request.app.state.settings)


def get_presets(request: Request) -> ShippedPresets:
    settings: Settings = request.app.state.settings
    return load_shipped_presets(settings.curated_dir)


def get_default_plan(request: Request) -> TalentPlan:
    settings: Settings = request.app.state.settings
    return load_default_plan(settings.curated_dir / "talent_plan.yaml")


def get_default_rules(request: Request) -> UsageRules:
    settings: Settings = request.app.state.settings
    return load_rules(settings.curated_dir / "recommend.yaml")


DefaultRulesDep = Annotated[UsageRules, Depends(get_default_rules)]


def get_rules(session: SessionDep, default: DefaultRulesDep) -> UsageRules:
    """The Upgrades rules in use: edited in the app, or recommend.yaml (ADR 0016)."""
    return current_rules(session, default)


def get_enchant_data(request: Request) -> EnchantData:
    settings: Settings = request.app.state.settings
    return load_enchant_data(settings.curated_dir / "enchants.yaml")


def equipped_items(session: Session) -> dict[str, EquippedItem]:
    equipment = latest_by_kind(session).get("equipment")
    return {item.slot: item for item in parse_equipment(equipment.payload if equipment else None)}


class Pin(BaseModel):
    item_id: Annotated[int, Field(gt=0)]
    slot: str


class ChoiceUpdate(BaseModel):
    choice: ChoiceKind
    name: Annotated[str, Field(min_length=1, max_length=120)]


Weight = Annotated[float, Field(ge=-10, le=10, allow_inf_nan=False)]


class WeightsUpdate(BaseModel):
    weights: dict[str, Weight]


class NewPreset(BaseModel):
    name: str
    # The weights to save; leave out to copy the active preset.
    weights: dict[str, Weight] = {}


class PresetRename(BaseModel):
    name: str


class PresetChoice(BaseModel):
    key: str


def clean_weights(update: WeightsUpdate | NewPreset) -> dict[str, float]:
    if any(not name.strip() or len(name.strip()) > 40 for name in update.weights):
        raise HTTPException(422, "Stat names must be 1-40 characters")
    return {name.strip(): value for name, value in update.weights.items()}


PresetsDep = Annotated[ShippedPresets, Depends(get_presets)]
TargetsDep = Annotated[GearTargets, Depends(get_targets)]
RulesDep = Annotated[UsageRules, Depends(get_rules)]
DefaultPlanDep = Annotated[TalentPlan, Depends(get_default_plan)]
EnchantDataDep = Annotated[EnchantData, Depends(get_enchant_data)]


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    http: httpx.Client | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings, engine and mocked HTTP client; a
    real run (no settings given) also sets up logging (ADR 0019)."""
    if settings is None:
        settings = get_settings()
        configure_logging(settings, "api")
    engine = engine or make_engine(settings.database_url)
    pending_states: dict[str, float] = {}  # state -> created_at

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            "Starting character-planner %s: database %s, curated data in %s, frontend %s, "
            "log level %s%s",
            app_version(),
            safe_database_url(settings.database_url),
            settings.curated_dir,
            "built" if (settings.frontend_dist / "index.html").is_file() else "not built",
            settings.log_level,
            f", log files in {settings.log_dir}" if settings.log_dir else "",
        )
        init_db(engine)
        with Session(engine) as session:
            if migrate_stored_weights(session):
                logger.info("Moved saved stat weights into the Leveling tank preset")
            if moved := jobs.migrate_target_choices(session, settings):
                logger.info("Moved %d pinned items into the gear targets", moved)
        yield

    app = FastAPI(title="Character Planner", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Any]) -> Response:
        """Give each request an id, log it to the access log, and turn an unhandled error
        into one logged line and a 500 that carries the id (ADR 0019)."""
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else uuid4().hex[:12]
        token = request_id.set(rid)
        started = time.perf_counter()
        try:
            try:
                response: Response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error in %s %s", request.method, request.url.path)
                response = JSONResponse(
                    {"detail": "Internal server error", "request_id": rid}, status_code=500
                )
            response.headers["X-Request-ID"] = rid
            elapsed_ms = (time.perf_counter() - started) * 1000
            query = f"?{request.url.query}" if request.url.query else ""
            # The container health check runs every 30 seconds: only at DEBUG.
            level = logging.DEBUG if request.url.path == "/api/healthz" else logging.INFO
            access_logger.log(
                level,
                '%s "%s %s%s" %d %.0fms [%s]',
                request.client.host if request.client else "-",
                request.method,
                request.url.path,
                query,
                response.status_code,
                elapsed_ms,
                rid,
            )
            return response
        finally:
            request_id.reset(token)

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
    def sync(session: SessionDep) -> dict[str, int]:
        """Pull every endpoint and store each response, failures included.

        Then look up any target items not in the item catalog yet. That step is
        best-effort: a catalog failure never fails the sync.
        """
        try:
            return sync_character(session, settings, http=http)
        except NotLoggedIn as error:
            raise HTTPException(401, str(error)) from error

    @app.post("/api/items/refresh")
    def refresh_items(session: SessionDep, gear: TargetsDep, force: bool = False) -> RefreshResult:
        """Refresh item data from every source. force=true refetches everything.

        Source failures are reported in `errors` rather than failing the request.
        """
        return refresh_item_sources(
            session, settings, gear, equipped_item_ids(session), force=force, http=http
        )

    @app.post("/api/pool/refresh")
    def refresh_item_pool(
        session: SessionDep,
        force: bool = False,
        level: Annotated[int | None, Query(ge=1, le=80)] = None,
    ) -> PoolRefresh:
        """Refresh dungeon drop tables and quest rewards, then item details for a level
        window: `level`'s (guest mode asks for its own), else the character's, else the
        whole pool. The first run takes a few minutes (paced under Forever Companion's
        rate limit); `uv run character-planner-pool` does the same with progress output.
        """
        return jobs.refresh_item_pool(session, settings, force=force, http=http, level=level)

    @app.post("/api/enchants/refresh")
    def refresh_enchants(session: SessionDep, force: bool = False) -> RecipeRefresh:
        """Enchant recipes from Blizzard's profession data, plus their reagents and crafted
        items from Forever Companion (ADR 0010)."""
        return refresh_enchant_data(session, settings, force=force, http=http)

    @app.get("/api/enchants")
    def enchant_catalog(
        session: SessionDep, data: EnchantDataDep, include_sod: bool = False
    ) -> list[EnchantOption]:
        """Every enchant recipe that maps to a gear slot, with parsed effects."""
        return catalog(
            session,
            companion_by_id(session),
            include_sod=include_sod,
            data=data,
            equipped_effects=equipped_effects(equipped_items(session).values()),
        )

    @app.get("/api/enchants/recommendations")
    def enchant_recommendations(
        session: SessionDep, data: EnchantDataDep, presets: PresetsDep, rules: RulesDep
    ) -> EnchantAdvice:
        """Best enchants in reach per slot, against the one on now (ADR 0010)."""
        equipped = equipped_items(session)
        professions = latest_by_kind(session).get("professions")
        options = catalog(
            session,
            companion_by_id(session),
            data=data,
            equipped_effects=equipped_effects(equipped.values()),
        )
        return advise(
            options,
            equipped,
            current_weights(session, presets),
            rules,
            character_context(session)[0],
            known_recipe_ids(professions.payload if professions else None),
            data,
        )

    @app.get("/api/pool")
    def item_pool(session: SessionDep) -> PoolView:
        """Dungeon drops and quest rewards for the character's level window."""
        level, faction = character_context(session)
        return pool_view(session, level, faction)

    @app.get("/api/progress")
    def progress_over_time(session: SessionDep, presets: PresetsDep) -> Progress:
        """One point per sync, plus gear changes and level-ups (ADR 0008)."""
        return progress(session, current_weights(session, presets))

    @app.get("/api/recommendations")
    def recommendations(
        session: SessionDep, targets: TargetsDep, presets: PresetsDep, rules: RulesDep
    ) -> Recommendations:
        """Best upgrades in reach for each slot, from the item pool (ADR 0007)."""
        level, faction = character_context(session)
        icons = icons_by_id(session)
        equipment = latest_by_kind(session).get("equipment")
        equipped = {
            item.slot: item.model_copy(update={"icon_url": icons.get(item.item_id or 0)})
            for item in parse_equipment(equipment.payload if equipment else None)
        }
        return recommend(
            pool_view(session, level, faction),
            equipped,
            current_weights(session, presets),
            rules,
            targets,
            stored_choices(session),
        )

    @app.get("/api/choices")
    def get_choices(session: SessionDep) -> list[ItemChoiceView]:
        """Items dismissed in the app, newest first (ADR 0012)."""
        return list_choices(session)

    @app.put("/api/choices/{item_id}")
    def put_choice(
        item_id: Annotated[int, FastAPIPath(gt=0)], update: ChoiceUpdate, session: SessionDep
    ) -> list[ItemChoiceView]:
        """Dismiss an item: never suggest it. Pinning is POST /api/targets/pins."""
        set_choice(session, item_id, update.name.strip() or str(item_id), update.choice)
        return list_choices(session)

    @app.delete("/api/choices/{item_id}")
    def delete_choice(
        item_id: Annotated[int, FastAPIPath(gt=0)], session: SessionDep
    ) -> list[ItemChoiceView]:
        """Suggest a dismissed item again."""
        if not clear_choice(session, item_id):
            raise HTTPException(404, f"No choice stored for item {item_id}")
        return list_choices(session)

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
        """The gear targets in use: edited in the app, or gear_targets.yaml (ADR 0014)."""
        return gear

    def targets_changed(session: Session) -> GearTargets:
        return jobs.gear_targets(session, settings)

    @app.put("/api/targets")
    def put_targets(edited: EditedTargets, session: SessionDep) -> GearTargets:
        """Replace the gear targets. Priority follows each slot's order."""
        try:
            save_targets(session, edited.to_targets())
        except TargetsError as error:
            raise HTTPException(422, str(error)) from error
        return targets_changed(session)

    @app.delete("/api/targets")
    def delete_targets(session: SessionDep) -> GearTargets:
        """Go back to data/curated/gear_targets.yaml."""
        reset_targets(session)
        return targets_changed(session)

    @app.post("/api/targets/pins")
    def post_pin(pin: Pin, session: SessionDep, gear: TargetsDep) -> GearTargets:
        """Pin a pool item as a target ("Make target")."""
        faction = character_context(session)[1]
        item = next(
            (i for i in pool_view(session, None, faction).items if i.item_id == pin.item_id), None
        )
        if item is None:
            raise HTTPException(404, f"Item {pin.item_id} isn't in the item pool")
        try:
            save_targets(session, pin_target(gear, item, pin.slot))
        except TargetsError as error:
            raise HTTPException(422, str(error)) from error
        return targets_changed(session)

    @app.delete("/api/targets/pins/{item_id}")
    def delete_pin(
        item_id: Annotated[int, FastAPIPath(gt=0)], session: SessionDep, gear: TargetsDep
    ) -> GearTargets:
        """Take the pin off a target ("Unpin"); it stays a target."""
        unpinned = unpin_target(gear, item_id)
        if unpinned is None:
            raise HTTPException(404, f"Item {item_id} isn't a pinned target")
        save_targets(session, unpinned)
        return targets_changed(session)

    @app.get("/api/summary.md", response_class=PlainTextResponse)
    def summary(session: SessionDep, gear: TargetsDep, presets: PresetsDep) -> str:
        name = f"{settings.character_name} {settings.character_surname}"
        return build_summary(
            name,
            latest_by_kind(session),
            gear,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, presets),
            jobs.item_levels(session),
        )

    @app.get("/api/character")
    def character(session: SessionDep) -> CharacterView:
        return character_view(latest_by_kind(session), icons_by_id(session))

    @app.get("/api/gear")
    def gear(session: SessionDep, targets: TargetsDep, presets: PresetsDep) -> GearPlan:
        plan = gear_plan(
            latest_by_kind(session),
            targets,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, presets),
            jobs.item_levels(session),
        )
        return plan.model_copy(update={"targets_customised": targets_customised(session)})

    def preset_errors(action: Callable[[], object]) -> None:
        try:
            action()
        except UnknownPreset as error:
            raise HTTPException(404, f"No preset {error}") from error
        except PresetError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/weights")
    def get_weights(session: SessionDep, presets: PresetsDep) -> WeightsView:
        """The active preset's weights, its defaults and every preset (ADR 0013)."""
        return weights_view(session, presets)

    @app.put("/api/weights")
    def put_weights(update: WeightsUpdate, session: SessionDep, presets: PresetsDep) -> WeightsView:
        """Replace the active preset's weights. Stats left out fall back to their default."""
        weights = clean_weights(update)
        save_weights(session, presets, weights)
        return weights_view(session, presets)

    @app.delete("/api/weights")
    def delete_weights(session: SessionDep, presets: PresetsDep) -> WeightsView:
        """Reset the active shipped preset to its curated file."""
        preset_errors(lambda: reset_weights(session, presets))
        return weights_view(session, presets)

    @app.put("/api/weights/active")
    def put_active_preset(
        choice: PresetChoice, session: SessionDep, presets: PresetsDep
    ) -> WeightsView:
        """Switch presets: every score uses the active one."""
        preset_errors(lambda: activate(session, presets, choice.key))
        return weights_view(session, presets)

    @app.post("/api/weights/presets", status_code=201)
    def post_preset(new: NewPreset, session: SessionDep, presets: PresetsDep) -> WeightsView:
        """Save weights as a preset of your own ("Save as") and switch to it."""
        weights = clean_weights(new) if new.weights else current_weights(session, presets).weights
        preset_errors(lambda: create_preset(session, presets, new.name, weights))
        return weights_view(session, presets)

    @app.patch("/api/weights/presets/{key}")
    def patch_preset(
        key: str, rename: PresetRename, session: SessionDep, presets: PresetsDep
    ) -> WeightsView:
        """Rename a preset of your own."""
        preset_errors(lambda: rename_preset(session, presets, key, rename.name))
        return weights_view(session, presets)

    @app.delete("/api/weights/presets/{key}")
    def delete_weight_preset(key: str, session: SessionDep, presets: PresetsDep) -> WeightsView:
        """Delete a preset of your own; if it was active, Leveling tank takes over."""
        preset_errors(lambda: delete_preset(session, presets, key))
        return weights_view(session, presets)

    def talents_view(session: Session, default: TalentPlan) -> TalentPlanView:
        latest = latest_by_kind(session)
        profile, specs = latest.get("profile"), latest.get("specializations")
        plan = current_plan(session, default)
        return compare(
            plan,
            parse_specialization(specs.payload if specs else None),
            character_level(profile.payload if profile else None),
            customised=plan != default,
        )

    @app.get("/api/guest")
    def get_guest_options(presets: PresetsDep) -> GuestOptions:
        """What guest mode offers: classes with rules and the shipped weight presets."""
        return guest_options(presets)

    @app.get("/api/guest/recommendations")
    def get_guest_recommendations(
        session: SessionDep,
        rules: DefaultRulesDep,
        presets: PresetsDep,
        level: Annotated[int, Query(ge=1, le=80)],
        class_key: Annotated[str, Query(alias="class")] = "warrior",
        faction: Faction = "alliance",
        preset: str | None = None,
    ) -> Recommendations:
        """Guest mode (ADR 0017): the best items per slot and dungeons for a class and
        level, from the shipped rules and weights. Reads no character data; stores nothing."""
        try:
            return guest_recommendations(
                session,
                rules,
                presets,
                class_key=class_key,
                level=level,
                faction=faction,
                preset=preset,
            )
        except GuestError as error:
            raise HTTPException(422, str(error)) from error

    def destination_or_404(session: Session, destination_id: int) -> NotificationDestination:
        destination = session.get(NotificationDestination, destination_id)
        if destination is None:
            raise HTTPException(404, f"No notification destination {destination_id}")
        return destination

    @app.get("/api/notifications")
    def get_notifications(session: SessionDep) -> notify.NotificationsView:
        """Alert destinations (webhook URLs masked), the alerts on offer, recent sends."""
        return notify.notifications_view(session)

    @app.post("/api/notifications/destinations", status_code=201)
    def post_destination(
        new: notify.NewDestination, session: SessionDep
    ) -> notify.NotificationsView:
        """Add a Discord webhook destination (#12)."""
        try:
            notify.add_destination(session, new)
        except notify.NotifyError as error:
            raise HTTPException(422, str(error)) from error
        return notify.notifications_view(session)

    @app.patch("/api/notifications/destinations/{destination_id}")
    def patch_destination(
        destination_id: int, update: notify.DestinationUpdate, session: SessionDep
    ) -> notify.NotificationsView:
        destination = destination_or_404(session, destination_id)
        try:
            notify.update_destination(session, destination, update)
        except notify.NotifyError as error:
            raise HTTPException(422, str(error)) from error
        return notify.notifications_view(session)

    @app.delete("/api/notifications/destinations/{destination_id}")
    def delete_destination(destination_id: int, session: SessionDep) -> notify.NotificationsView:
        notify.remove_destination(session, destination_or_404(session, destination_id))
        return notify.notifications_view(session)

    @app.post("/api/notifications/destinations/{destination_id}/test")
    def test_destination(destination_id: int, session: SessionDep) -> notify.SendResult:
        """Send a test message to the destination now."""
        destination = destination_or_404(session, destination_id)
        if http is not None:
            return notify.send_test(session, settings, destination, http)
        with notify.new_client() as client:
            return notify.send_test(session, settings, destination, client)

    @app.get("/api/rules")
    def get_rules_view(session: SessionDep, default: DefaultRulesDep) -> RulesView:
        """The Upgrades rules, their defaults, and what the editor can offer (ADR 0016)."""
        return rules_view(session, default)

    @app.put("/api/rules")
    def put_rules(edited: EditedRules, session: SessionDep, default: DefaultRulesDep) -> RulesView:
        """Replace the Upgrades rules."""
        try:
            save_rules(session, edited.to_rules())
        except RulesError as error:
            raise HTTPException(422, str(error)) from error
        return rules_view(session, default)

    @app.delete("/api/rules")
    def delete_rules(session: SessionDep, default: DefaultRulesDep) -> RulesView:
        """Go back to data/curated/recommend.yaml."""
        reset_rules(session)
        return rules_view(session, default)

    @app.get("/api/talents")
    def get_talents(session: SessionDep, default: DefaultPlanDep) -> TalentPlanView:
        """The talent plan compared with the synced talents (ADR 0009)."""
        return talents_view(session, default)

    @app.put("/api/talents/plan")
    def put_talent_plan(
        plan: TalentPlan, session: SessionDep, default: DefaultPlanDep
    ) -> TalentPlanView:
        """Replace the talent plan."""
        save_plan(session, plan)
        return talents_view(session, default)

    @app.delete("/api/talents/plan")
    def delete_talent_plan(session: SessionDep, default: DefaultPlanDep) -> TalentPlanView:
        """Go back to data/curated/talent_plan.yaml."""
        reset_plan(session)
        return talents_view(session, default)

    # Serve the built frontend (npm run build) from the same origin, after every API
    # route so those win. In development Vite serves it instead and proxies to us.
    if (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

    return app
