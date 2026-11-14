"""Work the API and the worker share: syncing the character and refreshing static data.

The API runs these when you press a button; the worker (worker.py, ADR 0011) runs them on
a schedule. Each takes a session and settings, so neither caller owns the logic.
"""

import logging
import time

import httpx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import notify
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.characters import first_character, refresh_from_profile
from character_planner.choices import take_target_choices
from character_planner.classes import character_class_name, current_defaults
from character_planner.config import Settings
from character_planner.crafting import crafted_items, refresh_crafting
from character_planner.curated import GearTargets
from character_planner.db import (
    Character,
    CompanionDungeon,
    RecipeData,
    Snapshot,
    StoredToken,
    latest_by_kind,
)
from character_planner.dungeons import stored_dungeons
from character_planner.enchants import RecipeRefresh, refresh_enchant_data
from character_planner.items import refresh_item_sources
from character_planner.leases import Busy, lease
from character_planner.pool import (
    PoolItem,
    PoolRefresh,
    build_pool,
    level_window,
    pool_view,
    refresh_pool,
    resolve_target_ids,
)
from character_planner.rares import stored_rares
from character_planner.recommend import PAIRED, SLOT_FOR
from character_planner.retention import forget_character, prune
from character_planner.talent_trees import TalentRefresh, refresh_talent_trees, stored_tree
from character_planner.targets import current_targets, pin_target, save_targets
from character_planner.tokens import CredentialsError, app_token
from character_planner.views import character_faction, character_level, parse_equipment

logger = logging.getLogger(__name__)


def current_id(session: Session) -> int | None:
    """The current character's id, for shared refreshes; None before there is one."""
    character = first_character(session)
    return character.id if character else None


def current_token(session: Session) -> oauth.Token | None:
    """The user's login token while it's valid. Syncs don't need it (#107): only the
    account's character list does."""
    stored = session.get(StoredToken, 1)
    if stored is None:
        return None
    token = oauth.Token(stored.access_token, stored.expires_at, stored.scope)
    return None if token.expired else token


def character_context(session: Session, character_id: int | None) -> tuple[int | None, str | None]:
    """Level and faction from the latest profile snapshot."""
    profile = latest_by_kind(session, character_id).get("profile")
    payload = profile.payload if profile else None
    return character_level(payload), character_faction(payload)


def equipped_item_ids(session: Session, character_id: int | None) -> list[int]:
    equipment = latest_by_kind(session, character_id).get("equipment")
    items = parse_equipment(equipment.payload) if equipment else []
    return [item.item_id for item in items if item.item_id is not None]


def default_targets(session: Session, settings: Settings, character_id: int | None) -> GearTargets:
    """The synced class's shipped targets (#80): gear_targets.yaml for a Warrior."""
    return current_defaults(session, settings.curated_dir, character_id).targets


def gear_targets(session: Session, settings: Settings, character_id: int | None) -> GearTargets:
    """The edited targets, or gear_targets.yaml (ADR 0014), with item ids filled in from
    the item pool where it has them."""
    targets = current_targets(
        session, default_targets(session, settings, character_id), character_id
    )
    pool = build_pool(
        stored_dungeons(session),
        character_context(session, character_id)[1],
        rares=stored_rares(session),
    )
    return resolve_target_ids(targets, pool)


def item_levels(session: Session, character_id: int | None) -> dict[int, int]:
    """Each pool item's own level (required level, else its quest or dungeon level), to
    place targets that don't name a level (ADR 0015)."""
    faction = character_context(session, character_id)[1]
    return {
        item.item_id: item.effective_level
        for item in pool_view(session, None, faction, crafted_items(session, character_id)).items
        if item.effective_level is not None
    }


def pool_slot(item: PoolItem) -> str | None:
    """The equipment slot an item would go in (the first of a ring or trinket pair)."""
    slot = item.item_slot or ""
    return PAIRED[slot][0] if slot in PAIRED else SLOT_FOR.get(slot)


def migrate_target_choices(session: Session, settings: Settings, character_id: int | None) -> int:
    """Move items pinned before ADR 0014 into the targets."""
    ids = take_target_choices(session, character_id)
    if not ids:
        return 0
    faction = character_context(session, character_id)[1]
    view = pool_view(session, None, faction, crafted_items(session, character_id))
    pool = {item.item_id: item for item in view.items}
    targets, moved = gear_targets(session, settings, character_id), 0
    for item_id in ids:
        item = pool.get(item_id)
        slot = pool_slot(item) if item else None
        if item is None or slot is None:
            logger.warning("Dropped pinned item %s: it's not in the item pool", item_id)
            continue
        targets, moved = pin_target(targets, item, slot), moved + 1
    if moved:
        save_targets(session, targets, character_id)
    return moved


def sync_character(
    session: Session, settings: Settings, character: Character, http: httpx.Client | None = None
) -> dict[str, int]:
    """Pull every character endpoint and store each response, failures included.

    Uses the app's own token, so no login is needed and syncs never stop at 24 hours
    (#107). A 401 means Blizzard no longer takes the cached token: get a new one and try
    once more. A second 401 means the client itself is refused, so CredentialsError, as
    when the client ID and secret are missing or wrong. Other failures (a 404 for a
    character that doesn't exist, 403, 429, 5xx) are stored and reported, not retried.

    Then look up any target items not in the item catalog yet. That step is best-effort:
    a catalog failure never fails the sync.
    """
    started = time.perf_counter()
    character_id = character.id
    logger.info("Sync %s: started", character.slug)
    token = app_token(session, settings, http)
    with BlizzardClient(settings, token, http=http) as client:
        results = client.all_character_data(character.slug, character.region)
    if any(r.status == 401 for r in results):
        logger.warning("Sync: Battle.net refused the app token (401); trying a new one")
        token = app_token(session, settings, http, renew=True)
        with BlizzardClient(settings, token, http=http) as client:
            results = client.all_character_data(character.slug, character.region)
        if any(r.status == 401 for r in results):
            raise CredentialsError(
                "Battle.net refused a new app token too (HTTP 401): check BNET_CLIENT_ID, "
                "BNET_CLIENT_SECRET and BNET_REGION"
            )
    profile = next((r for r in results if r.kind == "profile"), None)
    if profile is not None and profile.status == 404:
        logger.warning(
            "Sync: character %s not found in the %s region: check its name and region",
            character.slug,
            character.region,
        )
        # Blizzard's terms: a character that no longer exists is deleted (#131, ADR 0034).
        # Only when the stored data is about this same character, never on a typo.
        forget_character(session, character)
    for result in results:
        session.add(
            Snapshot(
                character_id=character_id,
                source="api",
                kind=result.kind,
                status=result.status,
                payload=result.body,
            )
        )
    session.flush()
    refresh_from_profile(session, character)
    session.commit()
    failed = sorted(f"{r.kind} ({r.status})" for r in results if not 200 <= r.status < 300)
    level, _ = character_context(session, character_id)
    logger.info(
        "Sync %s: %d endpoints stored in %.1fs, level %s%s",
        character.slug,
        len(results),
        time.perf_counter() - started,
        level if level is not None else "unknown",
        f", failed: {', '.join(failed)}" if failed else "",
    )
    targets = gear_targets(session, settings, character_id)
    # Its own progress and errors are logged by the item search and lookups.
    refresh_item_sources(
        session, settings, targets, equipped_item_ids(session, character_id), http=http
    )
    refresh_crafted_gear(session, settings, character_id, http)
    send_sync_alerts(session, settings, character)
    prune_old_data(session)
    return {result.kind: result.status for result in results}


def prune_old_data(session: Session) -> None:
    """Delete Blizzard data older than 30 days (#131). Best effort after a sync: the
    worker's daily job runs it too."""
    try:
        prune(session)
    except Exception:
        session.rollback()
        logger.exception("Pruning data older than 30 days failed")


def refresh_crafted_gear(
    session: Session,
    settings: Settings,
    character_id: int | None,
    http: httpx.Client | None = None,
) -> None:
    """The recipes the character knows and the items they make (#10). Best effort, as the
    item catalog step: a failure is logged, never fails the sync."""
    try:
        result = refresh_crafting(session, settings, character_id, http=http)
    except Exception:
        session.rollback()
        logger.exception("Crafted gear refresh after the sync failed")
        return
    for error in result.errors:
        logger.warning("Crafted gear: %s", error)


def send_sync_alerts(session: Session, settings: Settings, character: Character) -> None:
    """Queue alerts for what this sync changed and send them now (#12). Best effort: an
    alert problem never fails the sync; the worker retries what's left."""
    try:
        if notify.after_sync(session, settings, character):
            with notify.new_client() as client:
                notify.deliver_due(session, client)
    except Exception:
        session.rollback()
        logger.exception("Notifications after the sync failed")


def refresh_item_pool(
    session: Session,
    settings: Settings,
    *,
    force: bool = False,
    http: httpx.Client | None = None,
    level: int | None = None,
) -> PoolRefresh:
    """The item pool refresh, one at a time across processes (#87); raises leases.Busy
    when it's already running."""
    with lease(_engine(session), "pool"):
        return _refresh_item_pool(session, settings, force=force, http=http, level=level)


def refresh_enchants(
    session: Session, settings: Settings, *, force: bool = False, http: httpx.Client | None = None
) -> RecipeRefresh:
    """The enchant data refresh (ADR 0010), one at a time across processes (#87)."""
    with lease(_engine(session), "enchants"):
        return refresh_enchant_data(session, settings, force=force, http=http)


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


def missing_data(session: Session, character_id: int | None) -> list[str]:
    """Static data a fresh instance hasn't loaded yet: "pool" (no dungeon data),
    "enchants" (no recipes), "talents" (no trees for the synced class, #88)."""
    missing: list[str] = []
    if session.exec(select(CompanionDungeon)).first() is None:
        missing.append("pool")
    if session.exec(select(RecipeData)).first() is None:
        missing.append("enchants")
    class_name = character_class_name(session, character_id)
    if class_name and stored_tree(session, class_name) is None:
        missing.append("talents")
    return missing


def refresh_talents(
    session: Session,
    settings: Settings,
    character_id: int | None,
    *,
    http: httpx.Client | None = None,
) -> TalentRefresh | None:
    """The synced class's talent trees (#88), one refresh at a time; None before a sync
    (no class to fetch for)."""
    class_name = character_class_name(session, character_id)
    if class_name is None:
        return None
    with lease(_engine(session), "talents"):
        return refresh_talent_trees(session, settings, class_name, http=http)


def load_missing_data(engine: Engine, settings: Settings, http: httpx.Client | None = None) -> None:
    """Load what a fresh instance is missing, in the background after the first sync
    (#87). Skips anything already running (the worker may be on it)."""
    with Session(engine) as session:
        # Shared data, loaded for the current character's class and level (ADR 0036).
        character_id = current_id(session)
        missing = missing_data(session, character_id)
        if not missing:
            return
        logger.info("First data load: %s", ", ".join(missing))
        for name in missing:
            try:
                if name == "pool":
                    refresh_item_pool(session, settings, http=http)
                elif name == "talents":
                    refresh_talents(session, settings, character_id, http=http)
                else:
                    refresh_enchants(session, settings, http=http)
            except Busy:
                logger.info("First data load: the %s refresh is already running", name)
            except Exception:
                session.rollback()
                logger.exception("First data load: the %s refresh failed", name)


def _refresh_item_pool(
    session: Session,
    settings: Settings,
    *,
    force: bool = False,
    http: httpx.Client | None = None,
    level: int | None = None,
) -> PoolRefresh:
    """Dungeon drop tables and quest rewards, then item details for a level window.

    The window is around `level` when given (guest mode's level, #48), else the
    character's. Without either, every pool item: about 1,700 requests, ~20 minutes.
    """
    # The pool is shared; its window follows the current character (ADR 0036).
    character_level, faction = character_context(session, current_id(session))
    asked = level is not None
    level = level if level is not None else character_level
    started = time.perf_counter()
    if level is None:
        # No synced character (guest mode on a fresh install): every pool item's details.
        logger.info(
            "Item pool refresh: no character level, so fetching details for the whole pool%s",
            " (forced)" if force else "",
        )
    else:
        logger.info(
            "Item pool refresh: level %s (%s), window %s, faction %s%s",
            level,
            "asked for" if asked else "the character's",
            level_window(level),
            faction or "any",
            " (forced)" if force else "",
        )
    result = refresh_pool(
        session,
        level=level,
        faction=faction,
        force=force,
        http=http,
        pause=settings.companion_request_pause,
    )
    logger.info(
        "Item pool refresh: done in %.1fs, %d dungeons fetched of %d listed, pool %d items "
        "(%d wanted), %d item details fetched, %d not found, %d quest chain steps fetched, "
        "%d rares and %d class quests listed, %d errors",
        time.perf_counter() - started,
        result.dungeons_fetched,
        result.dungeons_listed,
        result.pool_size,
        result.in_window,
        result.items_fetched,
        len(result.items_not_found),
        result.quests_fetched,
        result.rares_listed,
        result.class_quests_listed,
        len(result.errors),
    )
    return result
