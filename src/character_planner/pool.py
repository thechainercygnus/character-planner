"""The item pool: every dungeon drop and dungeon quest reward, with where it comes from.

Built from Forever Companion's per-dungeon data (ADR 0006). Item details (stats, armor,
item level) come from GET /items/{id} as before (ADR 0004), fetched only for items in
the character's level window so a refresh stays a few hundred requests.

The pool is what the engine will pick gear targets from (phase C). For now it also fills
in item_id for gear targets that only name their item.
"""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, computed_field
from sqlmodel import Session

from character_planner.companion import CompanionInfo, companion_by_id, refresh_companion
from character_planner.curated import GearTargets
from character_planner.dungeons import (
    REQUEST_PAUSE,
    Dungeon,
    Progress,
    new_client,
    refresh_dungeons,
    stored_dungeons,
)

# Dungeons this far below / above the character's level are in the window.
LEVELS_BELOW = 3
LEVELS_ABOVE = 10
# Item stats rarely change; refetching hundreds of items daily would be wasteful.
POOL_ITEM_MAX_AGE = timedelta(days=7)


class PoolSource(BaseModel):
    kind: Literal["drop", "quest"]
    dungeon_id: str
    dungeon: str
    min_level: int | None = None
    max_level: int | None = None
    detail: str | None = None  # the boss for a drop, the quest for a reward
    choice: bool = False  # a quest reward picked from several
    quest_min_level: int | None = None  # level needed to pick the quest up


class PoolItem(BaseModel):
    item_id: int
    name: str
    slot: str | None = None
    quality: str | None = None
    sources: list[PoolSource] = []
    # From GET /items/{id}, once fetched.
    item_slot: str | None = None  # the item's own slot: One-Hand, Held In Off-hand...
    weapon_type: str | None = None
    item_level: int | None = None
    required_level: int | None = None
    armor_type: str | None = None
    armor: int | None = None
    stats: dict[str, int] = {}
    dps: float | None = None
    icon_url: str | None = None
    wowhead: str | None = None

    @computed_field
    @property
    def effective_level(self) -> int | None:
        """The level this item can be had at: its required level, else (many quest rewards
        have none) the easiest source's level. A dungeon quest needs both its pickup level
        and the dungeon, so it counts the higher of the two."""
        if self.required_level is not None:
            return self.required_level
        levels = [
            max((lvl for lvl in (s.quest_min_level, s.min_level) if lvl is not None), default=None)
            for s in self.sources
        ]
        return min((lvl for lvl in levels if lvl is not None), default=None)

    @property
    def lowest_dungeon_level(self) -> int:
        levels = [s.min_level for s in self.sources if s.min_level is not None]
        return min(levels, default=0)


class PoolRefresh(BaseModel):
    dungeons_listed: int = 0
    dungeons_fetched: int = 0
    pool_size: int = 0
    in_window: int = 0
    items_fetched: int = 0
    items_not_found: list[int] = []
    errors: list[str] = []


class PoolView(BaseModel):
    level: int | None
    faction: str | None
    window: tuple[int, int] | None
    items: list[PoolItem]


def _can_take(quest_faction: str, faction: str | None) -> bool:
    return faction is None or quest_faction in ("both", faction)


def _source(
    dungeon: Dungeon,
    kind: Literal["drop", "quest"],
    detail: str | None,
    choice: bool = False,
    quest_min_level: int | None = None,
) -> PoolSource:
    return PoolSource(
        kind=kind,
        dungeon_id=dungeon.id,
        dungeon=dungeon.name,
        min_level=dungeon.min_level,
        max_level=dungeon.max_level,
        detail=detail,
        choice=choice,
        quest_min_level=quest_min_level,
    )


def build_pool(dungeons: Iterable[Dungeon], faction: str | None = None) -> dict[int, PoolItem]:
    """Every drop, and every quest reward this faction can take, keyed by item id."""
    pool: dict[int, PoolItem] = {}

    def add(
        item_id: int, name: str, source: PoolSource, slot: str | None, quality: str | None
    ) -> None:
        item = pool.setdefault(item_id, PoolItem(item_id=item_id, name=name))
        item.slot = item.slot or slot
        item.quality = item.quality or quality
        if source not in item.sources:
            item.sources.append(source)

    for dungeon in dungeons:
        for loot in dungeon.loot:
            add(
                loot.item_id,
                loot.name,
                _source(dungeon, "drop", loot.boss),
                loot.slot,
                loot.quality,
            )
        for reward in dungeon.rewards:
            if _can_take(reward.faction, faction):
                quest = _source(
                    dungeon, "quest", reward.quest, reward.choice, reward.min_level or reward.level
                )
                add(reward.item_id, reward.name, quest, None, None)
    return pool


def level_window(level: int) -> tuple[int, int]:
    return (level - LEVELS_BELOW, level + LEVELS_ABOVE)


def in_window(item: PoolItem, window: tuple[int, int]) -> bool:
    """Any source dungeon's level range overlaps the window (unknown ranges count)."""
    low, high = window
    return any(
        (s.min_level is None or s.min_level <= high) and (s.max_level is None or s.max_level >= low)
        for s in item.sources
    )


def slot_key(slot: str | None) -> str | None:
    """Item-detail slots ("Main Hand", "Waist") in the drop-table form ("main-hand")."""
    return slot.strip().lower().replace(" ", "-") if slot else None


def with_details(item: PoolItem, info: CompanionInfo | None) -> PoolItem:
    if info is None:
        return item
    return item.model_copy(
        update={
            # Quest rewards carry no slot in the dungeon data; the item details do.
            "slot": item.slot or slot_key(info.slot),
            "item_slot": info.slot,
            "weapon_type": info.weapon_type,
            "icon_url": info.icon_url,
            "wowhead": info.wowhead,
            "item_level": info.item_level,
            "required_level": info.required_level,
            "armor_type": info.armor_type,
            "armor": info.armor,
            "stats": info.stats,
            "dps": info.dps,
            "quality": item.quality or info.quality,
        }
    )


def pool_view(session: Session, level: int | None, faction: str | None) -> PoolView:
    """Pool items in the level window (all of them without a level), with item details."""
    pool = build_pool(stored_dungeons(session), faction)
    window = level_window(level) if level is not None else None
    details = companion_by_id(session)
    items = [
        with_details(item, details.get(item.item_id))
        for item in pool.values()
        if window is None or in_window(item, window)
    ]
    items.sort(key=lambda i: (i.lowest_dungeon_level, i.name))
    return PoolView(level=level, faction=faction, window=window, items=items)


def refresh_pool(
    session: Session,
    *,
    level: int | None,
    faction: str | None,
    force: bool = False,
    http: httpx.Client | None = None,
    pause: float = REQUEST_PAUSE,
    progress: Progress | None = None,
) -> PoolRefresh:
    """Refresh dungeon data, then fetch details for pool items in the level window.

    The first run is a few hundred requests paced under the rate limit (a few minutes);
    later runs only fetch what's stale.
    """
    own_http = http is None
    client = http or new_client()
    try:
        dungeons = refresh_dungeons(session, client, force=force, pause=pause, progress=progress)
        pool = build_pool(stored_dungeons(session), faction)
        window = level_window(level) if level is not None else None
        wanted = [i for i in pool.values() if window is None or in_window(i, window)]
        items = refresh_companion(
            session,
            [i.item_id for i in wanted],
            force=force,
            http=client,
            max_age=POOL_ITEM_MAX_AGE,
            pause=pause,
            progress=progress,
        )
    finally:
        if own_http:
            client.close()
    return PoolRefresh(
        dungeons_listed=dungeons.listed,
        dungeons_fetched=len(dungeons.fetched),
        pool_size=len(pool),
        in_window=len(wanted),
        items_fetched=len(items.fetched),
        items_not_found=items.not_found,
        errors=[f"Forever Companion {e}" for e in [*dungeons.errors, *items.errors]],
    )


def resolve_target_ids(targets: GearTargets, pool: Mapping[int, PoolItem]) -> GearTargets:
    """Fill in item_id for targets that only name their item, when exactly one pool
    item has that name. Ids already in the YAML always win."""
    by_name: dict[str, list[int]] = {}
    for item in pool.values():
        by_name.setdefault(item.name.casefold().strip(), []).append(item.item_id)

    brackets = []
    for bracket in targets.brackets:
        resolved = []
        for target in bracket.targets:
            matches = by_name.get(target.item.casefold().strip(), [])
            if target.item_id is None and len(matches) == 1:
                target = target.model_copy(update={"item_id": matches[0]})
            resolved.append(target)
        brackets.append(bracket.model_copy(update={"targets": resolved}))
    return targets.model_copy(update={"brackets": brackets})
