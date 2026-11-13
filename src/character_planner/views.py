"""Typed views over the latest snapshots: what the frontend and the summary read.

Snapshots stay raw JSON (ADR 0002). This module is the one place that knows the
Forever response shapes, confirmed against tests/fixtures/forever_*.json. Reads are
defensive: a missing or reshaped field becomes None instead of an error.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from character_planner import fields
from character_planner.companion import ATTRIBUTION as COMPANION_ATTRIBUTION
from character_planner.companion import CompanionInfo
from character_planner.curated import GearTarget, GearTargets
from character_planner.db import CatalogItem, Snapshot
from character_planner.scoring import Weights, score

# Short local names for the defensive readers.
_get = fields.get
_name = fields.name
_int = fields.as_int
_float = fields.as_float


# --- models ---------------------------------------------------------------------------


class ItemStat(BaseModel):
    name: str
    value: int


class Enchantment(BaseModel):
    """An enchant on an equipped item, as the equipment endpoint reports it."""

    text: str  # "Enchanted: Scope (+1 Damage)"
    enchantment_id: int | None = None
    source_item: str | None = None  # "Crude Scope"
    source_item_id: int | None = None
    kind: str | None = None  # enchantment_slot.type: PERMANENT (others not seen yet)


class EquippedItem(BaseModel):
    slot: str
    name: str
    item_id: int | None = None
    quality: str | None = None  # API quality type: POOR, COMMON, UNCOMMON, RARE, EPIC
    quality_name: str | None = None
    item_level: int | None = None
    armor_type: str | None = None  # item subclass: Cloth, Leather, Mail, Shield, Axe...
    armor: int | None = None
    stats: list[ItemStat] = []
    dps: float | None = None
    attack_speed: float | None = None  # seconds; weapons only
    enchantments: list[Enchantment] = []
    icon_url: str | None = None


class Stats(BaseModel):
    health: int | None = None
    strength: int | None = None
    agility: int | None = None
    stamina: int | None = None
    intellect: int | None = None
    spirit: int | None = None
    attack_power: int | None = None
    armor: int | None = None
    defense: int | None = None
    dodge: float | None = None
    parry: float | None = None
    block: float | None = None
    crit: float | None = None


class Profession(BaseModel):
    name: str
    skill: int | None = None
    max_skill: int | None = None
    primary: bool


class Talent(BaseModel):
    name: str
    rank: int | None = None
    description: str | None = None


class Specialization(BaseModel):
    name: str
    spent_points: int | None = None
    talents: list[Talent] = []


class CharacterView(BaseModel):
    name: str | None = None
    surname: str | None = None
    level: int | None = None
    race: str | None = None
    character_class: str | None = None
    guild: str | None = None
    # Average item level of the gear worn (not shirt, tabard or ammo), computed here: the
    # API's equipped_item_level counts empty slots too.
    equipped_item_level: float | None = None
    gear_slots_filled: int = 0
    captured_at: datetime | None = None
    stats: Stats | None = None
    professions: list[Profession] = []
    specialization: Specialization | None = None
    equipment: list[EquippedItem] = []


Verdict = Literal["reached", "upgrade", "sidegrade", "downgrade", "unknown"]


SourceName = Literal["blizzard", "companion", "manual"]


class TargetInfo(BaseModel):
    """What we know about a target item, merged from every source (ADR 0004).

    Precedence per field: manual (gear_targets.yaml) > Blizzard > Forever Companion.
    """

    sources: list[SourceName]
    item_id: int | None = None
    item_level: int | None = None
    required_level: int | None = None
    quality: str | None = None
    armor_type: str | None = None
    armor: int | None = None
    stats: list[ItemStat] = []
    dps: float | None = None
    icon_url: str | None = None
    drops: list[str] = []
    rewards: list[str] = []
    verified: int | None = None
    wowhead: str | None = None
    conflicts: list[str] = []


class UpcomingTarget(BaseModel):
    """A target above the character's level: shown early so you can prepare for it."""

    target: GearTarget
    target_info: TargetInfo | None
    level: int | None
    score_delta: float | None = None  # against what's worn now


class GearRow(BaseModel):
    slot: str
    equipped: EquippedItem | None
    target: GearTarget
    target_info: TargetInfo | None
    reached: bool
    verdict: Verdict
    item_level_delta: int | None
    armor_delta: int | None = None
    stat_deltas: dict[str, int] = {}
    score_delta: float | None = None
    verdict_basis: Literal["score", "item_level", "none"] = "none"
    warning: str | None
    level: int | None = None  # the level the target counts from (ADR 0015)
    upcoming: list[UpcomingTarget] = []  # the slot's next targets, nearest first


class SlotOutlook(BaseModel):
    """A slot whose targets are all above the character's level."""

    slot: str
    equipped: EquippedItem | None
    upcoming: list[UpcomingTarget]


class GearPlan(BaseModel):
    """Per slot (ADR 0015): the target to go for now, in rows, and what's coming up."""

    level: int | None
    rows: list[GearRow]
    later: list[SlotOutlook] = []  # slots with nothing to go for yet
    attributions: list[dict[str, str]] = []  # credits the data sources require
    targets_customised: bool = False  # edited in the app, not gear_targets.yaml (ADR 0014)


# --- parsers ----------------------------------------------------------------------------


def character_level(profile: Any) -> int | None:
    return _int(_get(profile, "level"))


# The 17 slots that hold gear with stats (not SHIRT, TABARD or AMMO).
GEAR_SLOTS = frozenset(
    {
        "HEAD",
        "NECK",
        "SHOULDER",
        "BACK",
        "CHEST",
        "WRIST",
        "HANDS",
        "WAIST",
        "LEGS",
        "FEET",
        "FINGER_1",
        "FINGER_2",
        "TRINKET_1",
        "TRINKET_2",
        "MAIN_HAND",
        "OFF_HAND",
        "RANGED",
    }
)


def average_item_level(equipment: list[EquippedItem]) -> float | None:
    """Mean item level of the gear worn, one decimal; None with nothing worn."""
    levels = [i.item_level for i in equipment if i.slot in GEAR_SLOTS and i.item_level is not None]
    return round(sum(levels) / len(levels), 1) if levels else None


def character_faction(profile: Any) -> str | None:
    """ "alliance" or "horde", lowercased to match Forever Companion's quest factions."""
    faction = _get(profile, "faction", "type")
    return faction.lower() if isinstance(faction, str) else None


def parse_equipment(equipment: Any) -> list[EquippedItem]:
    items = _get(equipment, "equipped_items")
    parsed: list[EquippedItem] = []
    for item in items if isinstance(items, list) else []:
        slot = _get(item, "slot", "type")
        name = _name(_get(item, "name"))
        if not (isinstance(slot, str) and name):
            continue
        stats = [
            ItemStat(name=stat_name, value=value)
            for stat in _get(item, "stats") or []
            if (stat_name := _name(_get(stat, "type", "name"))) is not None
            and (value := _int(_get(stat, "value"))) is not None
        ]
        parsed.append(
            EquippedItem(
                slot=slot,
                name=name,
                item_id=_int(_get(item, "item", "id")),
                quality=_get(item, "quality", "type"),
                quality_name=_name(_get(item, "quality", "name")),
                item_level=_int(_get(item, "level", "value")),
                armor_type=_name(_get(item, "item_subclass", "name")),
                armor=_int(_get(item, "armor", "value")),
                stats=stats,
                dps=_float(_get(item, "weapon", "dps", "value")),
                attack_speed=_seconds(_get(item, "weapon", "attack_speed", "value")),
                enchantments=parse_enchantments(_get(item, "enchantments")),
            )
        )
    return parsed


def _seconds(milliseconds: Any) -> float | None:
    value = _float(milliseconds)
    return round(value / 1000, 3) if value is not None else None


def parse_enchantments(enchantments: Any) -> list[Enchantment]:
    return [
        Enchantment(
            text=text,
            enchantment_id=_int(_get(e, "enchantment_id")),
            source_item=_name(_get(e, "source_item", "name")),
            source_item_id=_int(_get(e, "source_item", "id")),
            kind=_get(e, "enchantment_slot", "type"),
        )
        for e in (enchantments if isinstance(enchantments, list) else [])
        if (text := _name(_get(e, "display_string")))
    ]


def parse_stats(statistics: Any) -> Stats | None:
    if not isinstance(statistics, Mapping):
        return None
    return Stats(
        health=_int(_get(statistics, "health")),
        strength=_int(_get(statistics, "strength", "effective")),
        agility=_int(_get(statistics, "agility", "effective")),
        stamina=_int(_get(statistics, "stamina", "effective")),
        intellect=_int(_get(statistics, "intellect", "effective")),
        spirit=_int(_get(statistics, "spirit", "effective")),
        attack_power=_int(_get(statistics, "attack_power")),
        armor=_int(_get(statistics, "armor", "effective")),
        defense=_int(_get(statistics, "defense", "effective")),
        dodge=_float(_get(statistics, "dodge", "value")),
        parry=_float(_get(statistics, "parry", "value")),
        block=_float(_get(statistics, "block", "value")),
        crit=_float(_get(statistics, "melee_crit", "value")),
    )


def parse_professions(professions: Any) -> list[Profession]:
    parsed: list[Profession] = []
    for group, primary in (("primaries", True), ("secondaries", False)):
        for entry in _get(professions, group) or []:
            name = _name(_get(entry, "profession", "name"))
            if not name:
                continue
            tiers = _get(entry, "tiers") or [{}]
            tier = tiers[-1] if isinstance(tiers, list) and tiers else {}
            parsed.append(
                Profession(
                    name=name,
                    skill=_int(_get(tier, "skill_points")),
                    max_skill=_int(_get(tier, "max_skill_points")),
                    primary=primary,
                )
            )
    return parsed


def known_recipe_ids(professions: Any) -> set[int]:
    """Recipe ids the character knows, from every profession tier."""
    ids: set[int] = set()
    for group in ("primaries", "secondaries"):
        for entry in _get(professions, group) or []:
            for tier in _get(entry, "tiers") or []:
                for recipe in _get(tier, "known_recipes") or []:
                    if (recipe_id := _int(_get(recipe, "id"))) is not None:
                        ids.add(recipe_id)
    return ids


def parse_specialization(specializations: Any) -> Specialization | None:
    groups = _get(specializations, "specialization_groups") or []
    active = next((g for g in groups if _get(g, "is_active")), None)
    specs = _get(active, "specializations") or []
    # Classic-style talents: the tree with the most points is "the" spec.
    best = max(specs, key=lambda s: _int(_get(s, "spent_points")) or 0, default=None)
    name = _name(_get(best, "specialization_name"))
    if not name:
        return None
    return Specialization(
        name=name,
        spent_points=_int(_get(best, "spent_points")),
        talents=[
            Talent(
                name=talent_name,
                rank=_int(_get(t, "talent_rank")),
                description=_name(_get(t, "spell_tooltip", "description")),
            )
            for t in _get(best, "talents") or []
            if (talent_name := _name(_get(t, "talent", "name")))
        ],
    )


# --- views ------------------------------------------------------------------------------


def _payload(latest: Mapping[str, Snapshot], kind: str) -> Any:
    snapshot = latest.get(kind)
    return snapshot.payload if snapshot else None


def character_view(
    latest: Mapping[str, Snapshot], icons: Mapping[int, str] | None = None
) -> CharacterView:
    icons = icons or {}
    profile = _payload(latest, "profile")
    equipment = parse_equipment(_payload(latest, "equipment"))
    return CharacterView(
        name=_name(_get(profile, "name")),
        surname=_name(_get(profile, "surname")),
        level=character_level(profile),
        race=_name(_get(profile, "race", "name")),
        character_class=_name(_get(profile, "character_class", "name")),
        guild=_name(_get(profile, "guild", "name")),
        equipped_item_level=average_item_level(equipment),
        gear_slots_filled=sum(1 for item in equipment if item.slot in GEAR_SLOTS),
        captured_at=max((s.captured_at for s in latest.values()), default=None),
        stats=parse_stats(_payload(latest, "statistics")),
        professions=parse_professions(_payload(latest, "professions")),
        specialization=parse_specialization(_payload(latest, "specializations")),
        equipment=[
            item.model_copy(update={"icon_url": icons.get(item.item_id or 0)}) for item in equipment
        ],
    )


# Item level differences within this band count as a sidegrade.
SIDEGRADE_BAND = 2
ARMOR_TIERS = {"Cloth": 1, "Leather": 2, "Mail": 3, "Plate": 4}


def _first[T](*values: T | None) -> T | None:
    return next((v for v in values if v is not None), None)


def target_info(
    target: GearTarget,
    catalog: Mapping[str, CatalogItem],
    icons: Mapping[int, str],
    companion: Mapping[int, CompanionInfo] | None = None,
) -> TargetInfo | None:
    """Merge Blizzard search, Forever Companion and manual data for one target."""
    entry = catalog.get(target.item.casefold().strip())
    blizzard = entry.payload if entry and entry.found else None
    item_id = _first(target.item_id, _int(_get(blizzard, "id")))
    comp = (companion or {}).get(item_id) if item_id is not None else None
    manual = target.has_manual_data

    sources: list[SourceName] = []
    if blizzard is not None:
        sources.append("blizzard")
    if comp is not None:
        sources.append("companion")
    if manual:
        sources.append("manual")
    if not sources:
        return None

    bz_level = _int(_get(blizzard, "level"))
    bz_armor_type = _name(_get(blizzard, "item_subclass", "name"))
    conflicts: list[str] = []
    if (
        comp
        and bz_level is not None
        and comp.item_level is not None
        and bz_level != comp.item_level
    ):
        conflicts.append(f"item level: Blizzard {bz_level}, Forever Companion {comp.item_level}")
    if (
        comp
        and bz_armor_type
        and comp.armor_type
        and bz_armor_type.casefold() != comp.armor_type.casefold()
    ):
        conflicts.append(
            f"armor type: Blizzard {bz_armor_type}, Forever Companion {comp.armor_type}"
        )

    stats = target.stats or (comp.stats if comp else {})
    return TargetInfo(
        sources=sources,
        item_id=item_id,
        item_level=_first(target.item_level, bz_level, comp.item_level if comp else None),
        required_level=_first(
            _int(_get(blizzard, "required_level")), comp.required_level if comp else None
        ),
        quality=_first(_get(blizzard, "quality", "type"), comp.quality if comp else None),
        armor_type=_first(target.armor_type, bz_armor_type, comp.armor_type if comp else None),
        armor=_first(target.armor, comp.armor if comp else None),
        stats=[ItemStat(name=name, value=value) for name, value in stats.items()],
        dps=comp.dps if comp else None,
        icon_url=_first(icons.get(item_id) if item_id else None, comp.icon_url if comp else None),
        drops=comp.drops if comp else [],
        rewards=comp.rewards if comp else [],
        verified=comp.verified if comp else None,
        wowhead=comp.wowhead if comp else None,
        conflicts=conflicts,
    )


def deltas(
    equipped: EquippedItem | None, info: TargetInfo | None
) -> tuple[int | None, dict[str, int]]:
    """Armor and stat change from swapping the equipped item for the target."""
    if equipped is None or info is None:
        return None, {}
    armor = (
        info.armor - (equipped.armor or 0)
        if info.armor is not None and (equipped.armor is not None or equipped.armor_type)
        else None
    )
    known_stats = info.stats or info.armor is not None  # stat lines were read for this item
    if not known_stats:
        return armor, {}
    worn = {s.name: s.value for s in equipped.stats}
    wanted = {s.name: s.value for s in info.stats}
    changes = {name: wanted.get(name, 0) - worn.get(name, 0) for name in {*worn, *wanted}}
    return armor, {name: change for name, change in sorted(changes.items()) if change}


# Score differences within this band count as a sidegrade.
SCORE_SIDEGRADE_BAND = 1.0


def has_stat_data(info: TargetInfo | None) -> bool:
    return info is not None and (info.armor is not None or bool(info.stats) or info.dps is not None)


def score_delta(
    slot: str, equipped: EquippedItem | None, info: TargetInfo | None, weights: Weights | None
) -> float | None:
    """Weighted score of the target minus the equipped item's; None without stat data."""
    if weights is None or info is None or not has_stat_data(info):
        return None
    target_score = score(
        weights,
        slot=slot,
        armor=info.armor,
        stats={s.name: s.value for s in info.stats},
        dps=info.dps,
    )
    worn_score = (
        score(
            weights,
            slot=slot,
            armor=equipped.armor,
            stats={s.name: s.value for s in equipped.stats},
            dps=equipped.dps,
        )
        if equipped is not None
        else 0.0
    )
    return round(target_score - worn_score, 2)


def judge(
    target: GearTarget,
    equipped: EquippedItem | None,
    info: TargetInfo | None,
    gain: float | None = None,
) -> tuple[Verdict, int | None, Literal["score", "item_level", "none"]]:
    """Verdict, item level change, and what the verdict was based on.

    A weighted score gain decides when both items' stats are known; otherwise item
    level does (ADR 0003, 0005).
    """
    if equipped is not None and equipped.name.casefold() == target.item.casefold():
        return "reached", 0, "none"
    target_level = info.item_level if info else None
    level_delta = (
        target_level - equipped.item_level
        if target_level is not None and equipped is not None and equipped.item_level is not None
        else None
    )
    if gain is not None:
        if gain > SCORE_SIDEGRADE_BAND:
            return "upgrade", level_delta, "score"
        if gain < -SCORE_SIDEGRADE_BAND:
            return "downgrade", level_delta, "score"
        return "sidegrade", level_delta, "score"
    if target_level is None:
        return "unknown", None, "none"
    if equipped is None:
        return "upgrade", None, "item_level"
    if level_delta is None:
        return "unknown", None, "none"
    if level_delta > SIDEGRADE_BAND:
        return "upgrade", level_delta, "item_level"
    if level_delta < -SIDEGRADE_BAND:
        return "downgrade", level_delta, "item_level"
    return "sidegrade", level_delta, "item_level"


def armor_warning(equipped: EquippedItem | None, info: TargetInfo | None) -> str | None:
    """Flag a target that is lighter armor than what's worn (Leather replacing Mail)."""
    if equipped is None or info is None:
        return None
    worn = ARMOR_TIERS.get(equipped.armor_type or "")
    wanted = ARMOR_TIERS.get(info.armor_type or "")
    if worn and wanted and wanted < worn:
        return f"{info.armor_type} replacing {equipped.armor_type}"
    return None


# How many targets above the character's level to show per slot.
UPCOMING_PER_SLOT = 3


def target_level(
    target: GearTarget, info: TargetInfo | None, item_levels: Mapping[int, int]
) -> int | None:
    """The level a target counts from: the planned level or the item's own level, whichever
    is higher (ADR 0015). The item's own level is its required level, else the pool's
    quest or dungeon level."""
    own = _first(
        info.required_level if info else None,
        item_levels.get(target.item_id) if target.item_id is not None else None,
    )
    levels = [lvl for lvl in (target.level, own) if lvl is not None]
    return max(levels, default=None)


def _wears(equipped: EquippedItem | None, target: GearTarget) -> bool:
    if equipped is None:
        return False
    if target.item_id is not None and equipped.item_id is not None:
        return target.item_id == equipped.item_id
    return equipped.name.casefold() == target.item.casefold()


def gear_plan(
    latest: Mapping[str, Snapshot],
    targets: GearTargets,
    catalog: Mapping[str, CatalogItem] | None = None,
    icons: Mapping[int, str] | None = None,
    companion: Mapping[int, CompanionInfo] | None = None,
    weights: Weights | None = None,
    item_levels: Mapping[int, int] | None = None,
) -> GearPlan:
    """Per slot, the target to go for now and the ones coming up (ADR 0015).

    A slot's targets are ordered by level, then priority. The current one is the last
    whose level the character has reached, or the one being worn when that's further
    along. Targets after it are coming up. Targets without any known level count as
    reachable now.
    """
    catalog = catalog or {}
    icons = icons or {}
    item_levels = item_levels or {}
    level = character_level(_payload(latest, "profile"))
    reached_level = level or 0
    equipped = {
        item.slot: item.model_copy(update={"icon_url": icons.get(item.item_id or 0)})
        for item in parse_equipment(_payload(latest, "equipment"))
    }

    rows: list[GearRow] = []
    later: list[SlotOutlook] = []
    for slot in targets.slots():
        worn = equipped.get(slot)
        chain = []
        for target in targets.for_slot(slot):
            info = target_info(target, catalog, icons, companion)
            chain.append((target, info, target_level(target, info, item_levels)))
        chain.sort(key=lambda entry: entry[2] or 0)  # stable: priority breaks ties
        available = [i for i, (_, _, lvl) in enumerate(chain) if (lvl or 0) <= reached_level]
        wearing = [i for i, (target, _, _) in enumerate(chain) if _wears(worn, target)]
        current = max([*available[-1:], *wearing[-1:]], default=-1)
        upcoming = [
            UpcomingTarget(
                target=target,
                target_info=info,
                level=lvl,
                score_delta=score_delta(slot, worn, info, weights),
            )
            for target, info, lvl in chain[current + 1 :][:UPCOMING_PER_SLOT]
        ]
        if current < 0:
            later.append(SlotOutlook(slot=slot, equipped=worn, upcoming=upcoming))
            continue
        target, info, lvl = chain[current]
        gain = score_delta(slot, worn, info, weights)
        verdict, delta, basis = judge(target, worn, info, gain)
        if _wears(worn, target):
            verdict, delta, basis = "reached", 0, "none"
        armor_delta, stat_deltas = deltas(worn, info)
        rows.append(
            GearRow(
                slot=slot,
                equipped=worn,
                target=target,
                target_info=info,
                reached=verdict == "reached",
                verdict=verdict,
                item_level_delta=delta,
                armor_delta=armor_delta,
                stat_deltas=stat_deltas,
                score_delta=gain,
                verdict_basis=basis,
                warning=armor_warning(worn, info),
                level=lvl,
                upcoming=upcoming,
            )
        )
    # Biggest gain first; rows without a score keep slot order after them, and reached
    # targets go last. The sort is stable.
    rows.sort(
        key=lambda r: (r.verdict == "reached", r.score_delta is None, -(r.score_delta or 0.0))
    )
    later.sort(key=lambda s: min((u.level or 0 for u in s.upcoming), default=0))
    shown = [*rows, *(u for s in later for u in s.upcoming), *(u for r in rows for u in r.upcoming)]
    uses_companion = any(r.target_info and "companion" in r.target_info.sources for r in shown)
    return GearPlan(
        level=level,
        rows=rows,
        later=later,
        attributions=[COMPANION_ATTRIBUTION] if uses_companion else [],
    )
