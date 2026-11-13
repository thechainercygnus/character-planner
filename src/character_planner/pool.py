"""The item pool: every dungeon drop, dungeon quest reward and rare drop, with where it
comes from.

Built from Forever Companion's per-dungeon data (ADR 0006) and its rares (ADR 0029).
Item details (stats, armor, item level) come from GET /items/{id} as before (ADR 0004),
fetched only for items in the character's level window so a refresh stays a few hundred
requests.

The pool is what the engine will pick gear targets from (phase C). For now it also fills
in item_id for gear targets that only name their item.
"""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, computed_field
from sqlmodel import Session

from character_planner.class_quests import refresh_class_quests
from character_planner.companion import CompanionInfo, companion_by_id, refresh_companion
from character_planner.crafting import CraftedItem, crafted_details
from character_planner.curated import GearTargets
from character_planner.dungeons import (
    REQUEST_PAUSE,
    Dungeon,
    Progress,
    new_client,
    refresh_dungeons,
    stored_dungeons,
)
from character_planner.quests import (
    QuestStep,
    chain_level,
    chain_steps,
    refresh_quests,
    stored_quests,
)
from character_planner.rares import Rare, refresh_rares, stored_rares

# Dungeons this far below / above the character's level are in the window.
LEVELS_BELOW = 3
LEVELS_ABOVE = 10
# Item stats rarely change; refetching hundreds of items daily would be wasteful.
POOL_ITEM_MAX_AGE = timedelta(days=7)


SourceKind = Literal["drop", "quest", "rare", "crafted"]


class PoolSource(BaseModel):
    kind: SourceKind
    dungeon_id: str | None = None  # None for a rare
    dungeon: str | None = None
    # The dungeon's level range, or the rare's (#6).
    min_level: int | None = None
    max_level: int | None = None
    detail: str | None = None  # the boss for a drop, the quest for a reward
    choice: bool = False  # a quest reward picked from several
    quest_min_level: int | None = None  # level needed to pick the quest up
    quest: QuestStep | None = None  # the reward's quest, described (#7)
    # The quests to do before it, earliest first; each step's quests side by side (#7).
    chain: list[list[QuestStep]] = []
    # A rare's drop (#6): the rare's id and name, its zone, how many spawn points.
    rare_id: str | None = None
    rare: str | None = None
    zone: str | None = None
    spawns: int | None = None
    elite: bool = False
    # Crafted from a recipe the character knows (#10): the profession and recipe.
    profession: str | None = None
    recipe: str | None = None

    @property
    def place(self) -> str:
        """Where it's had, in a word: the dungeon, the rare or the profession."""
        return self.dungeon or self.rare or self.profession or "?"

    @property
    def start_level(self) -> int | None:
        """The level this source opens at: a dungeon quest needs its pickup level, the
        dungeon and every earlier quest in its chain, so the highest of them."""
        levels = (self.quest_min_level, self.min_level, chain_level(self.chain))
        return max((lvl for lvl in levels if lvl is not None), default=None)


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
        have none) the easiest source's level (PoolSource.start_level)."""
        if self.required_level is not None:
            return self.required_level
        levels = [s.start_level for s in self.sources]
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
    quests_fetched: int = 0
    rares_listed: int = 0
    class_quests_listed: int = 0
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
    kind: SourceKind,
    detail: str | None,
    choice: bool = False,
    quest_min_level: int | None = None,
    quest: QuestStep | None = None,
    chain: list[list[QuestStep]] | None = None,
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
        quest=quest,
        chain=chain or [],
    )


def _crafted_source(item: CraftedItem) -> PoolSource:
    level = item.info.required_level
    return PoolSource(
        kind="crafted",
        profession=item.profession,
        recipe=item.recipe,
        min_level=level,
        max_level=level,
    )


def _rare_source(rare: Rare) -> PoolSource:
    return PoolSource(
        kind="rare",
        rare_id=rare.id,
        rare=rare.name,
        zone=rare.zone,
        min_level=rare.min_level,
        max_level=rare.max_level,
        spawns=rare.spawns,
        elite=rare.elite,
    )


def known_quests(
    dungeons: Iterable[Dungeon], fetched: Mapping[int, QuestStep] | None = None
) -> dict[int, QuestStep]:
    """Every quest Forever Companion describes: those fetched by id (chain steps outside
    dungeons, #7), and the dungeons' own."""
    known = dict(fetched or {})
    for dungeon in dungeons:
        for quest in dungeon.quests:
            if quest.quest_id is not None:
                known[quest.quest_id] = quest
    return known


def build_pool(
    dungeons: Iterable[Dungeon],
    faction: str | None = None,
    quests: Mapping[int, QuestStep] | None = None,
    rares: Iterable[Rare] = (),
    crafted: Iterable[CraftedItem] = (),
) -> dict[int, PoolItem]:
    """Every drop, every quest reward this faction can take, every drop of a rare this
    faction can reach, and every item the character can craft, keyed by item id.

    quests: chain steps fetched by id (quests.stored_quests); steps that are dungeon
    quests are described from the dungeons themselves. rares: rares.stored_rares (#6).
    crafted: crafting.crafted_items, the synced character's own (#10); never for a guest.
    """
    dungeons = list(dungeons)
    known = known_quests(dungeons, quests)
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
                    dungeon,
                    "quest",
                    reward.quest,
                    reward.choice,
                    reward.min_level or reward.level,
                    known.get(reward.quest_id) if reward.quest_id is not None else None,
                    chain_steps(reward.prerequisites, known),
                )
                add(reward.item_id, reward.name, quest, None, None)
    for rare in rares:
        if _can_take(rare.faction, faction):
            for loot in rare.loot:
                add(loot.item_id, loot.name, _rare_source(rare), loot.slot, loot.quality)
    for made in crafted:
        add(made.item_id, made.name, _crafted_source(made), slot_key(made.info.slot), None)
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


def undescribed_steps(dungeons: Iterable[Dungeon], items: Iterable[PoolItem]) -> list[int]:
    """Chain step ids of these items' quests that no dungeon describes: the ones to look
    up by id."""
    known = known_quests(dungeons)
    return [
        quest.quest_id
        for item in items
        for source in item.sources
        for step in source.chain
        for quest in step
        if quest.quest_id is not None and quest.quest_id not in known
    ]


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


def pool_view(
    session: Session,
    level: int | None,
    faction: str | None,
    crafted: Iterable[CraftedItem] = (),
) -> PoolView:
    """Pool items in the level window (all of them without a level), with item details.

    crafted: the character's craftable gear (#10), with its details from Blizzard. Guest
    mode passes none: it reads no character data (ADR 0017).
    """
    crafted = list(crafted)
    pool = build_pool(
        stored_dungeons(session),
        faction,
        stored_quests(session),
        stored_rares(session),
        crafted,
    )
    window = level_window(level) if level is not None else None
    # Forever Companion's details win; crafted items are the ones it doesn't list.
    details = {**crafted_details(crafted), **companion_by_id(session)}
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
    """Refresh dungeon data, then fetch details for pool items in the level window, and
    the quest chain steps their quests need that no dungeon describes (#7). The rare list
    is one request, merged into the stored rares (#6), and so is the class quest list (#8).

    The first run is a few hundred requests paced under the rate limit (a few minutes);
    later runs only fetch what's stale.
    """
    own_http = http is None
    client = http or new_client()
    try:
        dungeons = refresh_dungeons(session, client, force=force, pause=pause, progress=progress)
        rares = refresh_rares(session, client)
        # Not items, but Forever Companion's other one-request list, kept as current (#8).
        class_quests = refresh_class_quests(session, client)
        stored = stored_dungeons(session)
        pool = build_pool(stored, faction, rares=stored_rares(session))
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
        quests = refresh_quests(
            session,
            undescribed_steps(stored, wanted),
            force=force,
            http=client,
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
        quests_fetched=len(quests.fetched),
        rares_listed=rares.listed,
        class_quests_listed=class_quests.listed,
        errors=[
            f"Forever Companion {e}"
            for e in [
                *dungeons.errors,
                *rares.errors,
                *class_quests.errors,
                *items.errors,
                *quests.errors,
            ]
        ],
    )


def resolve_target_ids(targets: GearTargets, pool: Mapping[int, PoolItem]) -> GearTargets:
    """Fill in item_id for targets that only name their item, when exactly one pool
    item has that name. Ids already in the YAML always win."""
    by_name: dict[str, list[int]] = {}
    for item in pool.values():
        by_name.setdefault(item.name.casefold().strip(), []).append(item.item_id)

    resolved = []
    for target in targets.targets:
        matches = by_name.get(target.item.casefold().strip(), [])
        if target.item_id is None and len(matches) == 1:
            target = target.model_copy(update={"item_id": matches[0]})
        resolved.append(target)
    return targets.model_copy(update={"targets": resolved})
