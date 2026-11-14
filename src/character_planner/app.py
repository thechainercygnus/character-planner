"""FastAPI application.

Run locally with: uv run uvicorn character_planner.app:create_app --factory --reload
(--factory means importing this module never reads .env or touches the database.)
"""

import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from character_planner import fields, jobs, leases, notify
from character_planner.account import AccountCharacter, parse_account
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.characters import (
    CharacterList,
    CharacterSummary,
    DuplicateCharacter,
    NewCharacter,
    add_character,
    adopt_at_start,
    all_characters,
    character_list,
    current_character,
    delete_character,
    owned_characters,
)
from character_planner.choices import (
    ChoiceKind,
    ItemChoiceView,
    clear_choice,
    list_choices,
    set_choice,
    stored_choices,
)
from character_planner.class_quests import (
    ClassQuestChecklist,
    UnknownClassQuest,
    checklist,
    set_done,
)
from character_planner.classes import (
    ClassDefaults,
    character_class_name,
    current_defaults,
)
from character_planner.companion import ATTRIBUTION as COMPANION_ATTRIBUTION
from character_planner.companion import SOURCES as COMPANION_SOURCES
from character_planner.companion import companion_by_id
from character_planner.config import Settings, get_settings
from character_planner.crafting import (
    ProfessionData,
    ProfessionsView,
    crafted_items,
    load_profession_data,
    professions_view,
)
from character_planner.curated import GearTargets
from character_planner.db import (
    Character,
    NoCharacter,
    NotificationDestination,
    Snapshot,
    StoredToken,
    catalog_by_name,
    icons_by_id,
    init_db,
    latest_by_kind,
    make_engine,
)
from character_planner.dungeons import stored_dungeons
from character_planner.enchant_corrections import (
    CorrectionError,
    CorrectionsView,
    EffectsUpdate,
    LevelUpdate,
    PerSlotUpdate,
    corrections_view,
    reset_crafted_effects,
    reset_per_slot,
    reset_reagent_level,
    set_crafted_effects,
    set_per_slot,
    set_reagent_level,
    stored_corrections,
)
from character_planner.enchant_corrections import apply as apply_corrections
from character_planner.enchants import (
    EnchantAdvice,
    EnchantData,
    EnchantOption,
    RecipeRefresh,
    advise,
    catalog,
    equipped_effects,
    load_enchant_data,
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
    character_context,
    current_token,
    equipped_item_ids,
    gear_targets,
    sync_character,
)
from character_planner.logs import ACCESS_LOGGER, configure_logging, request_id, safe_database_url
from character_planner.lookahead import DEFAULT_LEVELS as DEFAULT_LOOK_AHEAD
from character_planner.lookahead import MAX_LEVELS as MAX_LOOK_AHEAD
from character_planner.lookahead import LookAhead, look_ahead
from character_planner.pool import (
    PoolRefresh,
    PoolView,
    pool_view,
)
from character_planner.progress import Progress, progress
from character_planner.recommend import Recommendations, UsageRules, recommend
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
    migrate_stored_weights,
    rename_preset,
    reset_weights,
    save_weights,
    weights_view,
)
from character_planner.summary import build_summary
from character_planner.talent_trees import ClassTree, TalentRefresh, stored_tree
from character_planner.talents import (
    TalentPlan,
    TalentPlanView,
    compare,
    current_plan,
    plan_problems,
    reset_plan,
    save_plan,
    with_talent_ids,
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
from character_planner.tokens import CredentialsError
from character_planner.users import (
    COOKIE as SESSION_COOKIE,
)
from character_planner.users import (
    SESSION_LENGTH,
    LastAdmin,
    SignupsClosed,
    delete_user,
    end_session,
    sign_in,
    start_session,
    user_for,
    user_token,
)
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
# On the 404 for an X-Character-Id that isn't (or isn't yours): the web app then forgets it.
UNKNOWN_CHARACTER = "X-Character-Unknown"
# With users on, what needs no sign-in (ADR 0037): health, the footer, who's signed in and
# guest mode, which reads no character data (ADR 0017).
PUBLIC_API = frozenset({"/api/healthz", "/api/about", "/api/me"})
PUBLIC_PREFIXES = ("/api/guest",)
# Instance-wide: the admin's alone. Alert webhooks are secret-like, so even reading them.
ADMIN_ALWAYS = ("/api/notifications",)
ADMIN_WRITES = (
    "/api/enchants/corrections",
    "/api/items/refresh",
    "/api/pool/refresh",
    "/api/enchants/refresh",
    "/api/talents/refresh",
)
# The header the web app sends with every request; state-changing ones need it (#124).
APP_HEADER = "X-Requested-With"
APP_HEADER_VALUE = "character-planner"
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

logger = logging.getLogger(__name__)
access_logger = logging.getLogger(ACCESS_LOGGER)
# An incoming X-Request-ID is reused when it looks like an id, so a proxy's id carries.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def app_version() -> str:
    try:
        return version("character-planner")
    except PackageNotFoundError:
        return "(not installed)"


class CreditLink(BaseModel):
    name: str
    url: str


class DataCredit(CreditLink):
    sources: list[CreditLink]  # where the credited site gathered the data


class About(BaseModel):
    version: str
    source_url: str
    data: DataCredit
    # The privacy notice's contact (#133); empty when the operator set none.
    operator_contact: str = ""


class Me(BaseModel):
    users: bool  # PLANNER_USERS: sign-in needed (ADR 0037)
    signed_in: bool
    admin: bool
    signups_open: bool


class AccountCharacters(BaseModel):
    characters: list[AccountCharacter]


class Erased(BaseModel):
    # Rows deleted per table; tables that were already empty are left out.
    removed: dict[str, int]


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


def get_user_id(request: Request) -> int | None:
    """The signed-in user, set by the users middleware; None when users are off."""
    return getattr(request.state, "user_id", None)


UserIdDep = Annotated[int | None, Depends(get_user_id)]


def get_character_id(
    request: Request,
    session: SessionDep,
    user_id: UserIdDep,
    selected: Annotated[int | None, Header(alias="X-Character-Id", gt=0)] = None,
) -> int | None:
    """The character this request is about (#14, ADR 0036): the one the X-Character-Id
    header names, else the first. With users on, only the signed-in user's characters
    count: another user's answers 404, like an unknown one (ADR 0037). None when there's
    no character yet."""
    settings: Settings = request.app.state.settings
    if selected is not None:
        character = session.get(Character, selected)
        if character is None or (settings.planner_users and character.user_id != user_id):
            # Marked, so the web app can drop a remembered choice that's gone (a fresh
            # database, another user's character) instead of failing every request.
            raise HTTPException(
                404, f"No character {selected}", headers={UNKNOWN_CHARACTER: "true"}
            )
        return selected
    if settings.planner_users:
        first = owned_characters(session, user_id)
        return first[0].id if first else None
    character = current_character(session, settings)
    return character.id if character else None


CharacterIdDep = Annotated[int | None, Depends(get_character_id)]


def get_targets(request: Request, session: SessionDep, character_id: CharacterIdDep) -> GearTargets:
    """gear_targets.yaml, with item ids filled in from the item pool where it has them."""
    return gear_targets(session, request.app.state.settings, character_id)


def get_class_defaults(
    request: Request, session: SessionDep, character_id: CharacterIdDep
) -> ClassDefaults:
    """The synced character's class's shipped defaults (#80, ADR 0023)."""
    settings: Settings = request.app.state.settings
    return current_defaults(session, settings.curated_dir, character_id)


ClassDefaultsDep = Annotated[ClassDefaults, Depends(get_class_defaults)]


def get_presets(defaults: ClassDefaultsDep) -> ShippedPresets:
    return defaults.presets


def get_default_plan(defaults: ClassDefaultsDep) -> TalentPlan:
    return defaults.talent_plan


def get_default_rules(defaults: ClassDefaultsDep) -> UsageRules:
    return defaults.rules


DefaultRulesDep = Annotated[UsageRules, Depends(get_default_rules)]


def get_rules(
    session: SessionDep, character_id: CharacterIdDep, default: DefaultRulesDep
) -> UsageRules:
    """The Upgrades rules in use: edited in the app, or recommend.yaml (ADR 0016)."""
    return current_rules(session, default, character_id)


def get_profession_data(request: Request) -> ProfessionData:
    settings: Settings = request.app.state.settings
    return load_profession_data(settings.curated_dir / "professions.yaml")


def get_shipped_enchant_data(request: Request) -> EnchantData:
    """data/curated/enchants.yaml as shipped."""
    settings: Settings = request.app.state.settings
    return load_enchant_data(settings.curated_dir / "enchants.yaml")


ShippedEnchantDataDep = Annotated[EnchantData, Depends(get_shipped_enchant_data)]


def get_enchant_data(session: SessionDep, shipped: ShippedEnchantDataDep) -> EnchantData:
    """The enchant data in use: enchants.yaml with corrections made in the app (#36)."""
    return apply_corrections(shipped, stored_corrections(session))


def equipped_items(session: Session, character_id: int | None) -> dict[str, EquippedItem]:
    equipment = latest_by_kind(session, character_id).get("equipment")
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


class ClassQuestUpdate(BaseModel):
    done: bool


class TalentTreeView(BaseModel):
    class_name: str | None  # the synced class; None before a sync
    tree: ClassTree | None  # None until the trees are loaded
    loading: bool  # a talent tree refresh is running


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
    owns_engine = engine is None
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
            # Seeds the first character from .env on a database that has none (ADR 0036).
            character = adopt_at_start(session, settings)
            character_id = character.id if character else None
            if migrate_stored_weights(session, character_id):
                logger.info("Moved saved stat weights into the Leveling tank preset")
            if moved := jobs.migrate_target_choices(session, settings, character_id):
                logger.info("Moved %d pinned items into the gear targets", moved)
        yield
        if owns_engine:  # a caller's engine is the caller's to close
            engine.dispose()

    app = FastAPI(title="Character Planner", lifespan=lifespan)

    @app.middleware("http")
    async def require_app_header(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """State-changing API requests must carry the header the web app sends (#124). A
        cross-site form can't set it, and a cross-site script would need a CORS
        preflight, which this app never grants."""
        if (
            request.method in STATE_CHANGING
            and request.url.path.startswith("/api/")
            and request.headers.get(APP_HEADER) != APP_HEADER_VALUE
        ):
            return JSONResponse(
                {"detail": f"Missing the {APP_HEADER} header the web app sends"},
                status_code=403,
            )
        return await call_next(request)

    @app.middleware("http")
    async def require_user(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """With users on (ADR 0037): every /api request but the public ones needs a
        signed-in user, and the instance-wide ones need the admin."""
        path = request.url.path
        if not settings.planner_users or not path.startswith("/api/"):
            return await call_next(request)
        with Session(engine) as db:
            user = user_for(db, request.cookies.get(SESSION_COOKIE))
        if user is not None:
            request.state.user_id = user.id
            request.state.is_admin = user.is_admin
        if path in PUBLIC_API or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if user is None:
            return JSONResponse({"detail": "Sign in with Battle.net"}, status_code=401)
        admin_only = path.startswith(ADMIN_ALWAYS) or (
            request.method in STATE_CHANGING and path.startswith(ADMIN_WRITES)
        )
        if admin_only and not user.is_admin:
            return JSONResponse({"detail": "Only the admin can do that"}, status_code=403)
        return await call_next(request)

    # Added last, so it runs first: an unknown Host never reaches the app (#124).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
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

    @app.exception_handler(NoCharacter)
    async def no_character(  # pyright: ignore[reportUnusedFunction]
        _request: Request, error: NoCharacter
    ) -> JSONResponse:
        """A setting saved before any character exists (ADR 0036)."""
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/about")
    def about() -> About:
        """What the page footer shows (#43): the data credits, the source link (AGPL) and
        the version. Needs no character data, so guest mode has it too."""
        return About(
            version=app_version(),
            source_url=settings.source_url,
            data=DataCredit(
                name=str(COMPANION_ATTRIBUTION["name"]),
                url=str(COMPANION_ATTRIBUTION["url"]),
                sources=[CreditLink(**source) for source in COMPANION_SOURCES],
            ),
            operator_contact=settings.operator_contact,
        )

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
        if not settings.planner_users:
            session.merge(StoredToken(id=1, **asdict(token)))
            session.commit()
            return RedirectResponse(settings.post_login_redirect, status_code=303)
        # Users on (ADR 0037): the account id from /profile/user/wow is who this is.
        with BlizzardClient(settings, token, http=http) as client:
            account = client.account_profile()
        account_id = fields.as_int(fields.get(account.body, "id")) if account.ok else None
        if account_id is None:
            raise HTTPException(
                502, f"Battle.net didn't say whose account this is ({account.status})"
            )
        try:
            user = sign_in(session, account_id, token, signups_open=settings.planner_signups)
        except SignupsClosed as error:
            raise HTTPException(403, str(error)) from error
        redirect = RedirectResponse(settings.post_login_redirect, status_code=303)
        redirect.set_cookie(
            SESSION_COOKIE,
            start_session(session, user),
            max_age=int(SESSION_LENGTH.total_seconds()),
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return redirect

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, session: SessionDep) -> Response:
        """Sign out: the session stops working at once (ADR 0037)."""
        end_session(session, request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.delete("/api/account")
    def delete_account(request: Request, session: SessionDep, user_id: UserIdDep) -> Response:
        """Delete the signed-in user and everything stored for them (#16, ADR 0037):
        their characters with all their data and settings, sessions and Battle.net token.
        Only with users on; the admin can't while others remain (409)."""
        if not settings.planner_users or user_id is None:
            raise HTTPException(404, "There are no user accounts on this instance")
        try:
            removed = delete_user(session, user_id)
        except LastAdmin as error:
            raise HTTPException(409, str(error)) from error
        response = JSONResponse({"removed": removed})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/api/me")
    def me(request: Request) -> Me:
        """Whether users are on, and who's signed in (ADR 0037). Public, so the page
        knows to offer the sign-in."""
        user_id = getattr(request.state, "user_id", None)
        return Me(
            users=settings.planner_users,
            signed_in=user_id is not None,
            admin=bool(getattr(request.state, "is_admin", False)),
            signups_open=settings.planner_signups,
        )

    @app.get("/api/status")
    def status(
        session: SessionDep, character_id: CharacterIdDep, user_id: UserIdDep
    ) -> dict[str, Any]:
        stored = session.get(StoredToken, 1)
        latest = latest_by_kind(session, character_id)
        character = session.get(Character, character_id) if character_id is not None else None
        last_profile = session.exec(
            select(Snapshot)
            .where(col(Snapshot.character_id) == character_id, Snapshot.kind == "profile")
            .order_by(desc(col(Snapshot.captured_at)), desc(col(Snapshot.id)))
        ).first()
        return {
            "character": character.slug if character else None,
            "namespace": f"profile-forever-{character.region}" if character else None,
            # Syncs use the app's own token (#107): they need the client, not a login.
            "can_sync": settings.has_credentials,
            # The last sync's answer for the character: True, False after a 404 (wrong
            # name, surname or region), None before any sync or after another failure.
            "character_found": (
                True
                if last_profile is not None and last_profile.status == 200
                else False
                if last_profile is not None and last_profile.status == 404
                else None
            ),
            # The optional Battle.net login: only the account's character list needs it.
            "logged_in": (
                user_token(session, user_id) if user_id is not None else current_token(session)
            )
            is not None,
            "token_expires_at": stored.expires_at if stored else None,
            "latest_snapshots": {k: s.captured_at.isoformat() for k, s in latest.items()},
            # Refreshes running now, from any process: "pool", "enchants" (#87).
            "refreshing": leases.running(engine),
        }

    @app.post("/api/sync")
    def sync(
        session: SessionDep, character_id: CharacterIdDep, background: BackgroundTasks
    ) -> dict[str, int]:
        """Pull every endpoint and store each response, failures included.

        Then look up any target items not in the item catalog yet. That step is
        best-effort: a catalog failure never fails the sync. On a fresh instance, the item
        pool and enchant data then load in the background (#87).
        """
        character = session.get(Character, character_id) if character_id is not None else None
        if character is None:
            raise HTTPException(409, "No character to sync: CHARACTER_NAME in .env names the first")
        try:
            statuses = sync_character(session, settings, character, http=http)
        except CredentialsError as error:
            # The app's own client is missing or refused: nothing a login would fix.
            raise HTTPException(503, str(error)) from error
        if jobs.missing_data(session, character_id):
            background.add_task(jobs.load_missing_data, engine, settings, http)
        return statuses

    @app.post("/api/items/refresh")
    def refresh_items(
        session: SessionDep, character_id: CharacterIdDep, gear: TargetsDep, force: bool = False
    ) -> RefreshResult:
        """Refresh item data from every source. force=true refetches everything.

        Source failures are reported in `errors` rather than failing the request.
        """
        return refresh_item_sources(
            session,
            settings,
            gear,
            equipped_item_ids(session, character_id),
            force=force,
            http=http,
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
        try:
            return jobs.refresh_item_pool(session, settings, force=force, http=http, level=level)
        except leases.Busy as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/enchants/refresh")
    def refresh_enchants(session: SessionDep, force: bool = False) -> RecipeRefresh:
        """Enchant recipes from Blizzard's profession data, plus their reagents and crafted
        items from Forever Companion (ADR 0010)."""
        try:
            return jobs.refresh_enchants(session, settings, force=force, http=http)
        except leases.Busy as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/enchants")
    def enchant_catalog(
        session: SessionDep,
        character_id: CharacterIdDep,
        data: EnchantDataDep,
        include_sod: bool = False,
    ) -> list[EnchantOption]:
        """Every enchant recipe that maps to a gear slot, with parsed effects."""
        return catalog(
            session,
            companion_by_id(session),
            include_sod=include_sod,
            data=data,
            equipped_effects=equipped_effects(equipped_items(session, character_id).values()),
        )

    @app.get("/api/enchants/corrections")
    def get_enchant_corrections(
        session: SessionDep, shipped: ShippedEnchantDataDep
    ) -> CorrectionsView:
        """Corrections to enchants.yaml made in the app, and the shipped values (#36)."""
        return corrections_view(session, shipped)

    @app.put("/api/enchants/corrections/materials/{item_id}")
    def put_material_level(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        update: LevelUpdate,
        session: SessionDep,
        shipped: ShippedEnchantDataDep,
    ) -> CorrectionsView:
        """Correct the level a material is commonly found from."""
        set_reagent_level(session, item_id, update.level)
        return corrections_view(session, shipped)

    @app.delete("/api/enchants/corrections/materials/{item_id}")
    def delete_material_level(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        session: SessionDep,
        shipped: ShippedEnchantDataDep,
    ) -> CorrectionsView:
        """Go back to the shipped level (or the item's own)."""
        if not reset_reagent_level(session, item_id):
            raise HTTPException(404, f"No correction for material {item_id}")
        return corrections_view(session, shipped)

    @app.put("/api/enchants/corrections/crafted/{item_id}")
    def put_crafted_effects(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        update: EffectsUpdate,
        session: SessionDep,
        shipped: ShippedEnchantDataDep,
    ) -> CorrectionsView:
        """Add or fix the effect of a crafted enchant (a scope, an armor kit)."""
        try:
            set_crafted_effects(session, item_id, update.effects)
        except CorrectionError as error:
            raise HTTPException(400, str(error)) from error
        return corrections_view(session, shipped)

    @app.delete("/api/enchants/corrections/crafted/{item_id}")
    def delete_crafted_effects(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        session: SessionDep,
        shipped: ShippedEnchantDataDep,
    ) -> CorrectionsView:
        """Go back to the shipped effect, or none."""
        if not reset_crafted_effects(session, item_id):
            raise HTTPException(404, f"No correction for crafted item {item_id}")
        return corrections_view(session, shipped)

    @app.put("/api/enchants/corrections/per-slot")
    def put_per_slot(
        update: PerSlotUpdate, session: SessionDep, shipped: ShippedEnchantDataDep
    ) -> CorrectionsView:
        """How many enchants to list per slot."""
        set_per_slot(session, update.per_slot)
        return corrections_view(session, shipped)

    @app.delete("/api/enchants/corrections/per-slot")
    def delete_per_slot(session: SessionDep, shipped: ShippedEnchantDataDep) -> CorrectionsView:
        """Go back to the shipped number."""
        if not reset_per_slot(session):
            raise HTTPException(404, "per_slot isn't corrected")
        return corrections_view(session, shipped)

    @app.get("/api/enchants/recommendations")
    def enchant_recommendations(
        session: SessionDep,
        character_id: CharacterIdDep,
        data: EnchantDataDep,
        presets: PresetsDep,
        rules: RulesDep,
    ) -> EnchantAdvice:
        """Best enchants in reach per slot, against the one on now (ADR 0010)."""
        equipped = equipped_items(session, character_id)
        professions = latest_by_kind(session, character_id).get("professions")
        options = catalog(
            session,
            companion_by_id(session),
            data=data,
            equipped_effects=equipped_effects(equipped.values()),
        )
        return advise(
            options,
            equipped,
            current_weights(session, presets, character_id),
            rules,
            character_context(session, character_id)[0],
            known_recipe_ids(professions.payload if professions else None),
            data,
        )

    @app.get("/api/pool")
    def item_pool(session: SessionDep, character_id: CharacterIdDep) -> PoolView:
        """Dungeon drops and quest rewards for the character's level window."""
        level, faction = character_context(session, character_id)
        return pool_view(session, level, faction, crafted_items(session, character_id))

    @app.get("/api/professions")
    def get_professions(
        session: SessionDep,
        character_id: CharacterIdDep,
        data: Annotated[ProfessionData, Depends(get_profession_data)],
    ) -> ProfessionsView:
        """Each synced profession: skill, rank, the next rank and crafted gear (#10)."""
        level = jobs.character_context(session, character_id)[0]
        return professions_view(session, data, level, character_id)

    @app.get("/api/progress")
    def progress_over_time(
        session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> Progress:
        """One point per sync, plus gear changes and level-ups (ADR 0008)."""
        return progress(session, current_weights(session, presets, character_id), character_id)

    @app.get("/api/recommendations")
    def recommendations(
        session: SessionDep,
        character_id: CharacterIdDep,
        targets: TargetsDep,
        presets: PresetsDep,
        rules: RulesDep,
    ) -> Recommendations:
        """Best upgrades in reach for each slot, from the item pool (ADR 0007)."""
        level, faction = character_context(session, character_id)
        icons = icons_by_id(session)
        equipment = latest_by_kind(session, character_id).get("equipment")
        equipped = {
            item.slot: item.model_copy(update={"icon_url": icons.get(item.item_id or 0)})
            for item in parse_equipment(equipment.payload if equipment else None)
        }
        return recommend(
            pool_view(session, level, faction, crafted_items(session, character_id)),
            equipped,
            current_weights(session, presets, character_id),
            rules,
            targets,
            stored_choices(session, character_id),
        )

    @app.get("/api/choices")
    def get_choices(session: SessionDep, character_id: CharacterIdDep) -> list[ItemChoiceView]:
        """Items dismissed in the app, newest first (ADR 0012)."""
        return list_choices(session, character_id)

    @app.put("/api/choices/{item_id}")
    def put_choice(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        update: ChoiceUpdate,
        session: SessionDep,
        character_id: CharacterIdDep,
    ) -> list[ItemChoiceView]:
        """Dismiss an item: never suggest it. Pinning is POST /api/targets/pins."""
        set_choice(
            session, item_id, update.name.strip() or str(item_id), update.choice, character_id
        )
        return list_choices(session, character_id)

    @app.delete("/api/choices/{item_id}")
    def delete_choice(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        session: SessionDep,
        character_id: CharacterIdDep,
    ) -> list[ItemChoiceView]:
        """Suggest a dismissed item again."""
        if not clear_choice(session, item_id, character_id):
            raise HTTPException(404, f"No choice stored for item {item_id}")
        return list_choices(session, character_id)

    @app.post("/api/snapshots/manual", status_code=201)
    def add_manual(
        entry: ManualSnapshot, session: SessionDep, character_id: CharacterIdDep
    ) -> dict[str, int | None]:
        """Fallback for data the API doesn't return: store it in the same shape, for the
        current character."""
        if character_id is None:
            raise HTTPException(409, "No character: CHARACTER_NAME in .env names the first")
        snapshot = Snapshot(
            character_id=character_id,
            source="manual",
            kind=entry.kind,
            status=200,
            payload=entry.payload,
        )
        session.add(snapshot)
        session.commit()
        return {"id": snapshot.id}

    @app.get("/api/snapshots/latest")
    def latest(session: SessionDep, character_id: CharacterIdDep) -> dict[str, Any]:
        return {
            kind: {
                "captured_at": s.captured_at.isoformat(),
                "source": s.source,
                "payload": s.payload,
            }
            for kind, s in latest_by_kind(session, character_id).items()
        }

    @app.get("/api/targets")
    def targets(gear: TargetsDep) -> GearTargets:
        """The gear targets in use: edited in the app, or gear_targets.yaml (ADR 0014)."""
        return gear

    def targets_changed(session: Session, character_id: int | None) -> GearTargets:
        return jobs.gear_targets(session, settings, character_id)

    @app.put("/api/targets")
    def put_targets(
        edited: EditedTargets, session: SessionDep, character_id: CharacterIdDep
    ) -> GearTargets:
        """Replace the gear targets. Priority follows each slot's order."""
        try:
            save_targets(session, edited.to_targets(), character_id)
        except TargetsError as error:
            raise HTTPException(422, str(error)) from error
        return targets_changed(session, character_id)

    @app.delete("/api/targets")
    def delete_targets(session: SessionDep, character_id: CharacterIdDep) -> GearTargets:
        """Go back to data/curated/gear_targets.yaml."""
        reset_targets(session, character_id)
        return targets_changed(session, character_id)

    @app.post("/api/targets/pins")
    def post_pin(
        pin: Pin, session: SessionDep, character_id: CharacterIdDep, gear: TargetsDep
    ) -> GearTargets:
        """Pin a pool item as a target ("Make target")."""
        faction = character_context(session, character_id)[1]
        item = next(
            (
                i
                for i in pool_view(
                    session, None, faction, crafted_items(session, character_id)
                ).items
                if i.item_id == pin.item_id
            ),
            None,
        )
        if item is None:
            raise HTTPException(404, f"Item {pin.item_id} isn't in the item pool")
        try:
            save_targets(session, pin_target(gear, item, pin.slot), character_id)
        except TargetsError as error:
            raise HTTPException(422, str(error)) from error
        return targets_changed(session, character_id)

    @app.delete("/api/targets/pins/{item_id}")
    def delete_pin(
        item_id: Annotated[int, FastAPIPath(gt=0)],
        session: SessionDep,
        character_id: CharacterIdDep,
        gear: TargetsDep,
    ) -> GearTargets:
        """Take the pin off a target ("Unpin"); it stays a target."""
        unpinned = unpin_target(gear, item_id)
        if unpinned is None:
            raise HTTPException(404, f"Item {item_id} isn't a pinned target")
        save_targets(session, unpinned, character_id)
        return targets_changed(session, character_id)

    @app.get("/api/summary.md", response_class=PlainTextResponse)
    def summary(
        session: SessionDep, character_id: CharacterIdDep, gear: TargetsDep, presets: PresetsDep
    ) -> str:
        character = session.get(Character, character_id) if character_id is not None else None
        name = f"{character.name} {character.surname}".strip() if character else "No character"
        return build_summary(
            name,
            latest_by_kind(session, character_id),
            gear,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, presets, character_id),
            jobs.item_levels(session, character_id),
        )

    @app.get("/api/character")
    def character(session: SessionDep, character_id: CharacterIdDep) -> CharacterView:
        return character_view(latest_by_kind(session, character_id), icons_by_id(session))

    @app.delete("/api/character")
    def erase(session: SessionDep, character_id: CharacterIdDep) -> Erased:
        """Stop tracking the character and delete everything stored for it (#133, #14):
        snapshots, history, plans and settings edited in the app. Other characters and
        shared game data stay. With none left, the next start tracks the character .env
        names again."""
        if character_id is None:
            return Erased(removed={})
        return Erased(removed=delete_character(session, character_id))

    @app.get("/api/characters")
    def characters(session: SessionDep, user_id: UserIdDep) -> CharacterList:
        """The tracked characters, for the header's switcher (#14): the signed-in user's
        when users are on. Requests pick one with X-Character-Id; without it they get
        default_id, the first."""
        if not settings.planner_users:
            current_character(session, settings)  # seeds the first from .env if there's none
        return character_list(session, user_id if settings.planner_users else None)

    @app.get("/api/account/characters")
    def account_characters(session: SessionDep, user_id: UserIdDep) -> AccountCharacters:
        """The characters on the signed-in Battle.net account (#15), to pick ones to
        track. Fetched each time and never stored: the list names every character on the
        account (ADR 0034). Needs the optional Battle.net sign-in."""
        token = user_token(session, user_id) if user_id is not None else current_token(session)
        if token is None:
            raise HTTPException(401, "Sign in with Battle.net to list your characters")
        with BlizzardClient(settings, token, http=http) as client:
            result = client.account_profile()
        if result.status == 401:
            raise HTTPException(401, "The Battle.net sign-in has expired: sign in again")
        if not result.ok:
            raise HTTPException(502, f"Battle.net answered {result.status} for the account")
        mine = (
            owned_characters(session, user_id)
            if settings.planner_users
            else all_characters(session)
        )
        tracked = {(c.region, c.slug) for c in mine}
        listed = [
            c.model_copy(update={"tracked": (c.region, c.slug) in tracked})
            for c in parse_account(result.body)
        ]
        return AccountCharacters(characters=listed)

    @app.post("/api/characters", status_code=201)
    def post_character(
        new: NewCharacter, session: SessionDep, user_id: UserIdDep
    ) -> CharacterSummary:
        """Track another character. Sync it (with its X-Character-Id) to fetch its data."""
        try:
            character = add_character(session, new, user_id)
        except DuplicateCharacter as error:
            raise HTTPException(409, str(error)) from error
        listed = character_list(session, user_id if settings.planner_users else None).characters
        return next(c for c in listed if c.id == character.id)

    def build_gear_plan(
        session: Session, character_id: int | None, targets: GearTargets, presets: ShippedPresets
    ) -> GearPlan:
        return gear_plan(
            latest_by_kind(session, character_id),
            targets,
            catalog_by_name(session),
            icons_by_id(session),
            companion_by_id(session),
            current_weights(session, presets, character_id),
            jobs.item_levels(session, character_id),
        )

    @app.get("/api/gear")
    def gear(
        session: SessionDep, character_id: CharacterIdDep, targets: TargetsDep, presets: PresetsDep
    ) -> GearPlan:
        plan = build_gear_plan(session, character_id, targets, presets)
        return plan.model_copy(
            update={"targets_customised": targets_customised(session, character_id)}
        )

    @app.get("/api/look-ahead")
    def get_look_ahead(
        session: SessionDep,
        character_id: CharacterIdDep,
        targets: TargetsDep,
        presets: PresetsDep,
        default_plan: DefaultPlanDep,
        professions: Annotated[ProfessionData, Depends(get_profession_data)],
        levels: Annotated[int, Query(ge=1, le=MAX_LOOK_AHEAD)] = DEFAULT_LOOK_AHEAD,
    ) -> LookAhead:
        """What each of the next `levels` levels brings (#4): dungeons opening, gear
        targets, talent points, class quests and profession ranks."""
        level, faction = jobs.character_context(session, character_id)
        return look_ahead(
            level,
            levels,
            faction=faction,
            dungeons=stored_dungeons(session),
            gear=build_gear_plan(session, character_id, targets, presets),
            talents=talents_view(session, character_id, default_plan),
            class_quests=checklist(session, character_id),
            professions=professions_view(session, professions, level, character_id),
        )

    def preset_errors(action: Callable[[], object]) -> None:
        try:
            action()
        except UnknownPreset as error:
            raise HTTPException(404, f"No preset {error}") from error
        except PresetError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/weights")
    def get_weights(
        session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> WeightsView:
        """The active preset's weights, its defaults and every preset (ADR 0013)."""
        return weights_view(session, presets, character_id)

    @app.put("/api/weights")
    def put_weights(
        update: WeightsUpdate,
        session: SessionDep,
        character_id: CharacterIdDep,
        presets: PresetsDep,
    ) -> WeightsView:
        """Replace the active preset's weights. Stats left out fall back to their default."""
        weights = clean_weights(update)
        save_weights(session, presets, weights, character_id)
        return weights_view(session, presets, character_id)

    @app.delete("/api/weights")
    def delete_weights(
        session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> WeightsView:
        """Reset the active shipped preset to its curated file."""
        preset_errors(lambda: reset_weights(session, presets, character_id))
        return weights_view(session, presets, character_id)

    @app.put("/api/weights/active")
    def put_active_preset(
        choice: PresetChoice, session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> WeightsView:
        """Switch presets: every score uses the active one."""
        preset_errors(lambda: activate(session, presets, choice.key, character_id))
        return weights_view(session, presets, character_id)

    @app.post("/api/weights/presets", status_code=201)
    def post_preset(
        new: NewPreset, session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> WeightsView:
        """Save weights as a preset of your own ("Save as") and switch to it."""
        weights = (
            clean_weights(new)
            if new.weights
            else current_weights(session, presets, character_id).weights
        )
        preset_errors(lambda: create_preset(session, presets, new.name, weights, character_id))
        return weights_view(session, presets, character_id)

    @app.patch("/api/weights/presets/{key}")
    def patch_preset(
        key: str,
        rename: PresetRename,
        session: SessionDep,
        character_id: CharacterIdDep,
        presets: PresetsDep,
    ) -> WeightsView:
        """Rename a preset of your own."""
        preset_errors(lambda: rename_preset(session, presets, key, rename.name, character_id))
        return weights_view(session, presets, character_id)

    @app.delete("/api/weights/presets/{key}")
    def delete_weight_preset(
        key: str, session: SessionDep, character_id: CharacterIdDep, presets: PresetsDep
    ) -> WeightsView:
        """Delete a preset of your own; if it was active, Leveling tank takes over."""
        preset_errors(lambda: delete_preset(session, presets, key, character_id))
        return weights_view(session, presets, character_id)

    def talents_view(
        session: Session, character_id: int | None, default: TalentPlan
    ) -> TalentPlanView:
        latest = latest_by_kind(session, character_id)
        profile, specs = latest.get("profile"), latest.get("specializations")
        stored = current_plan(session, default, character_id)
        # Ids filled in from the trees by name, for plans written before #88.
        plan = with_talent_ids(stored, talent_tree(session, character_id))
        return compare(
            plan,
            parse_specialization(specs.payload if specs else None),
            character_level(profile.payload if profile else None),
            customised=stored != default,
        )

    def talent_tree(session: Session, character_id: int | None) -> ClassTree | None:
        class_name = character_class_name(session, character_id)
        return stored_tree(session, class_name) if class_name else None

    @app.get("/api/guest")
    def get_guest_options() -> GuestOptions:
        """What guest mode offers: classes with shipped defaults, and their presets."""
        return guest_options(settings.curated_dir)

    @app.get("/api/guest/recommendations")
    def get_guest_recommendations(
        session: SessionDep,
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
                settings.curated_dir,
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
    def get_rules_view(
        session: SessionDep, character_id: CharacterIdDep, default: DefaultRulesDep
    ) -> RulesView:
        """The Upgrades rules, their defaults, and what the editor can offer (ADR 0016)."""
        return rules_view(session, default, character_id)

    @app.put("/api/rules")
    def put_rules(
        edited: EditedRules,
        session: SessionDep,
        character_id: CharacterIdDep,
        default: DefaultRulesDep,
    ) -> RulesView:
        """Replace the Upgrades rules."""
        try:
            save_rules(session, edited.to_rules(), character_id)
        except RulesError as error:
            raise HTTPException(422, str(error)) from error
        return rules_view(session, default, character_id)

    @app.delete("/api/rules")
    def delete_rules(
        session: SessionDep, character_id: CharacterIdDep, default: DefaultRulesDep
    ) -> RulesView:
        """Go back to data/curated/recommend.yaml."""
        reset_rules(session, character_id)
        return rules_view(session, default, character_id)

    @app.get("/api/class-quests")
    def get_class_quests(session: SessionDep, character_id: CharacterIdDep) -> ClassQuestChecklist:
        """The synced character's class quests: missed, now, soon, later and done (#8)."""
        return checklist(session, character_id)

    @app.put("/api/class-quests/{quest_id}")
    def put_class_quest(
        quest_id: Annotated[str, FastAPIPath(pattern=r"^[a-z0-9-]{1,100}$")],
        update: ClassQuestUpdate,
        session: SessionDep,
        character_id: CharacterIdDep,
    ) -> ClassQuestChecklist:
        """Mark a class quest done, or not done."""
        try:
            set_done(session, quest_id, update.done, character_id)
        except UnknownClassQuest:
            raise HTTPException(404, f"No class quest {quest_id}") from None
        return checklist(session, character_id)

    @app.get("/api/talents")
    def get_talents(
        session: SessionDep, character_id: CharacterIdDep, default: DefaultPlanDep
    ) -> TalentPlanView:
        """The talent plan compared with the synced talents (ADR 0009)."""
        return talents_view(session, character_id, default)

    @app.put("/api/talents/plan")
    def put_talent_plan(
        plan: TalentPlan, session: SessionDep, character_id: CharacterIdDep, default: DefaultPlanDep
    ) -> TalentPlanView:
        """Replace the talent plan. With the talent trees loaded, a plan that breaks their
        rules (unknown talents, prerequisites, points per row) is refused (#88)."""
        tree = talent_tree(session, character_id)
        problems = plan_problems(plan, tree)
        if problems:
            raise HTTPException(422, "; ".join(problems))
        save_plan(session, with_talent_ids(plan, tree), character_id)
        return talents_view(session, character_id, default)

    @app.get("/api/talents/tree")
    def get_talent_tree(session: SessionDep, character_id: CharacterIdDep) -> TalentTreeView:
        """The synced class's talent trees (#88). `tree` is null until they're loaded:
        after the first sync, in the background."""
        class_name = character_class_name(session, character_id)
        return TalentTreeView(
            class_name=class_name,
            tree=stored_tree(session, class_name) if class_name else None,
            loading="talents" in leases.running(engine),
        )

    @app.post("/api/talents/refresh")
    def refresh_talents(session: SessionDep, character_id: CharacterIdDep) -> TalentRefresh:
        """Fetch the synced class's talent trees and icons again."""
        try:
            result = jobs.refresh_talents(session, settings, character_id, http=http)
        except leases.Busy as error:
            raise HTTPException(409, str(error)) from error
        if result is None:
            raise HTTPException(409, "No synced character yet: sync first")
        return result

    @app.delete("/api/talents/plan")
    def delete_talent_plan(
        session: SessionDep, character_id: CharacterIdDep, default: DefaultPlanDep
    ) -> TalentPlanView:
        """Go back to data/curated/talent_plan.yaml."""
        reset_plan(session, character_id)
        return talents_view(session, character_id, default)

    # Serve the built frontend (npm run build) from the same origin, after every API
    # route so those win. In development Vite serves it instead and proxies to us.
    if (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

    return app
