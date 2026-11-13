"""Work the API and the worker share: syncing the character and refreshing static data.

The API runs these when you press a button; the worker (worker.py, ADR 0011) runs them on
a schedule. Each takes a session and settings, so neither caller owns the logic.
"""

import logging
import time

import httpx
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.choices import take_target_choices
from character_planner.config import Settings
from character_planner.curated import GearTargets, load_gear_targets
from character_planner.db import Snapshot, StoredToken, latest_by_kind
from character_planner.dungeons import stored_dungeons
from character_planner.items import refresh_item_sources
from character_planner.pool import (
    PoolItem,
    PoolRefresh,
    build_pool,
    level_window,
    pool_view,
    refresh_pool,
    resolve_target_ids,
)
from character_planner.recommend import PAIRED, SLOT_FOR
from character_planner.targets import current_targets, pin_target, save_targets
from character_planner.views import character_faction, character_level, parse_equipment

logger = logging.getLogger(__name__)


class NotLoggedIn(Exception):
    """No stored user token, or it has expired. Battle.net issues no refresh token for
    the authorization code flow, so only logging in again fixes it."""


def current_token(session: Session) -> oauth.Token | None:
    stored = session.get(StoredToken, 1)
    if stored is None:
        return None
    token = oauth.Token(stored.access_token, stored.expires_at, stored.scope)
    return None if token.expired else token


def character_context(session: Session) -> tuple[int | None, str | None]:
    """Level and faction from the latest profile snapshot."""
    profile = latest_by_kind(session).get("profile")
    payload = profile.payload if profile else None
    return character_level(payload), character_faction(payload)


def equipped_item_ids(session: Session) -> list[int]:
    equipment = latest_by_kind(session).get("equipment")
    items = parse_equipment(equipment.payload) if equipment else []
    return [item.item_id for item in items if item.item_id is not None]


def default_targets(settings: Settings) -> GearTargets:
    return load_gear_targets(settings.curated_dir / "gear_targets.yaml")


def gear_targets(session: Session, settings: Settings) -> GearTargets:
    """The edited targets, or gear_targets.yaml (ADR 0014), with item ids filled in from
    the item pool where it has them."""
    targets = current_targets(session, default_targets(settings))
    pool = build_pool(stored_dungeons(session), character_context(session)[1])
    return resolve_target_ids(targets, pool)


def item_levels(session: Session) -> dict[int, int]:
    """Each pool item's own level (required level, else its quest or dungeon level), to
    place targets that don't name a level (ADR 0015)."""
    faction = character_context(session)[1]
    return {
        item.item_id: item.effective_level
        for item in pool_view(session, None, faction).items
        if item.effective_level is not None
    }


def pool_slot(item: PoolItem) -> str | None:
    """The equipment slot an item would go in (the first of a ring or trinket pair)."""
    slot = item.item_slot or ""
    return PAIRED[slot][0] if slot in PAIRED else SLOT_FOR.get(slot)


def migrate_target_choices(session: Session, settings: Settings) -> int:
    """Move items pinned before ADR 0014 into the targets."""
    ids = take_target_choices(session)
    if not ids:
        return 0
    faction = character_context(session)[1]
    pool = {item.item_id: item for item in pool_view(session, None, faction).items}
    targets, moved = gear_targets(session, settings), 0
    for item_id in ids:
        item = pool.get(item_id)
        slot = pool_slot(item) if item else None
        if item is None or slot is None:
            logger.warning("Dropped pinned item %s: it's not in the item pool", item_id)
            continue
        targets, moved = pin_target(targets, item, slot), moved + 1
    if moved:
        save_targets(session, targets)
    return moved


def sync_character(
    session: Session, settings: Settings, http: httpx.Client | None = None
) -> dict[str, int]:
    """Pull every character endpoint and store each response, failures included.

    Then look up any target items not in the item catalog yet. That step is best-effort:
    a catalog failure never fails the sync. Raises NotLoggedIn without a valid token.
    """
    token = current_token(session)
    if token is None:
        logger.info("Sync skipped: not logged in, or the login has expired")
        raise NotLoggedIn("Not logged in or token expired; visit /auth/login")
    started = time.perf_counter()
    logger.info("Sync %s: started", settings.character_slug)
    with BlizzardClient(settings, token, http=http) as client:
        results = client.all_character_data()
    for result in results:
        session.add(
            Snapshot(source="api", kind=result.kind, status=result.status, payload=result.body)
        )
    session.commit()
    failed = sorted(f"{r.kind} ({r.status})" for r in results if not 200 <= r.status < 300)
    level, _ = character_context(session)
    logger.info(
        "Sync %s: %d endpoints stored in %.1fs, level %s%s",
        settings.character_slug,
        len(results),
        time.perf_counter() - started,
        level if level is not None else "unknown",
        f", failed: {', '.join(failed)}" if failed else "",
    )
    targets = gear_targets(session, settings)
    # Its own progress and errors are logged by the item search and lookups.
    refresh_item_sources(session, settings, targets, equipped_item_ids(session), http=http)
    return {result.kind: result.status for result in results}


def refresh_item_pool(
    session: Session, settings: Settings, *, force: bool = False, http: httpx.Client | None = None
) -> PoolRefresh:
    """Dungeon drop tables and quest rewards, then item details for the level window."""
    level, faction = character_context(session)
    started = time.perf_counter()
    if level is None:
        # No synced character (guest mode on a fresh install): every pool item's details.
        logger.info(
            "Item pool refresh: no character level, so fetching details for the whole pool%s",
            " (forced)" if force else "",
        )
    else:
        logger.info(
            "Item pool refresh: level %s, window %s, faction %s%s",
            level,
            level_window(level),
            faction or "unknown",
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
        "(%d wanted), %d item details fetched, %d not found, %d errors",
        time.perf_counter() - started,
        result.dungeons_fetched,
        result.dungeons_listed,
        result.pool_size,
        result.in_window,
        result.items_fetched,
        len(result.items_not_found),
        len(result.errors),
    )
    return result
