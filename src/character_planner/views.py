"""Typed views over the latest snapshots: what the frontend and the summary read.

Snapshots stay raw JSON (ADR 0002). This module is the one place that knows the
Forever response shapes, confirmed against tests/fixtures/forever_*.json. Reads are
defensive: a missing or reshaped field becomes None instead of an error.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from character_planner.curated import GearTarget, GearTargets
from character_planner.db import Snapshot


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _name(value: Any) -> str | None:
    """Localised names arrive as a string, or as {"en_US": ...} without a locale param."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return value.get("en_US") or next(iter(value.values()), None)
    return None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


# --- models ---------------------------------------------------------------------------


class ItemStat(BaseModel):
    name: str
    value: int


class EquippedItem(BaseModel):
    slot: str
    name: str
    item_id: int | None = None
    quality: str | None = None  # API quality type: POOR, COMMON, UNCOMMON, RARE, EPIC
    quality_name: str | None = None
    item_level: int | None = None
    armor: int | None = None
    stats: list[ItemStat] = []


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
    equipped_item_level: int | None = None
    captured_at: datetime | None = None
    stats: Stats | None = None
    professions: list[Profession] = []
    specialization: Specialization | None = None
    equipment: list[EquippedItem] = []


class GearRow(BaseModel):
    slot: str
    equipped: EquippedItem | None
    target: GearTarget
    reached: bool


class GearPlan(BaseModel):
    level: int | None
    bracket_min_level: int | None
    next_bracket_level: int | None
    next_bracket_size: int
    rows: list[GearRow]


# --- parsers ----------------------------------------------------------------------------


def character_level(profile: Any) -> int | None:
    return _int(_get(profile, "level"))


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
                armor=_int(_get(item, "armor", "value")),
                stats=stats,
            )
        )
    return parsed


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


def character_view(latest: Mapping[str, Snapshot]) -> CharacterView:
    profile = _payload(latest, "profile")
    return CharacterView(
        name=_name(_get(profile, "name")),
        surname=_name(_get(profile, "surname")),
        level=character_level(profile),
        race=_name(_get(profile, "race", "name")),
        character_class=_name(_get(profile, "character_class", "name")),
        guild=_name(_get(profile, "guild", "name")),
        equipped_item_level=_int(_get(profile, "equipped_item_level")),
        captured_at=max((s.captured_at for s in latest.values()), default=None),
        stats=parse_stats(_payload(latest, "statistics")),
        professions=parse_professions(_payload(latest, "professions")),
        specialization=parse_specialization(_payload(latest, "specializations")),
        equipment=parse_equipment(_payload(latest, "equipment")),
    )


def gear_plan(latest: Mapping[str, Snapshot], targets: GearTargets) -> GearPlan:
    level = character_level(_payload(latest, "profile"))
    equipped = {item.slot: item for item in parse_equipment(_payload(latest, "equipment"))}
    bracket = targets.for_level(level) if level is not None else None
    upcoming = targets.next_after(level) if level is not None else None

    ordered = sorted(
        bracket.targets if bracket else [],
        key=lambda t: (t.priority is None, t.priority or 0),
    )
    rows = [
        GearRow(
            slot=target.slot,
            equipped=equipped.get(target.slot),
            target=target,
            reached=(item := equipped.get(target.slot)) is not None and item.name == target.item,
        )
        for target in ordered
    ]
    return GearPlan(
        level=level,
        bracket_min_level=bracket.min_level if bracket else None,
        next_bracket_level=upcoming.min_level if upcoming else None,
        next_bracket_size=len(upcoming.targets) if upcoming else 0,
        rows=rows,
    )
