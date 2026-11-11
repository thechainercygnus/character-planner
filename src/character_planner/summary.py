"""Markdown character summary, for pasting into a Claude chat.

Rendering only: all parsing of API responses lives in views.py.
"""

from collections.abc import Mapping
from typing import Any

from character_planner.curated import GearTargets
from character_planner.db import Snapshot
from character_planner.views import (
    EquippedItem,
    character_level,
    character_view,
    gear_plan,
    parse_equipment,
)

__all__ = ["build_summary", "character_level", "equipped_by_slot"]


def _label(item: EquippedItem) -> str:
    return f"{item.name} ({item.quality_name})" if item.quality_name else item.name


def equipped_by_slot(equipment: Any) -> dict[str, str]:
    return {item.slot: _label(item) for item in parse_equipment(equipment)}


def _fmt(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "?"
    return f"{value:.1f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def build_summary(character: str, latest: Mapping[str, Snapshot], targets: GearTargets) -> str:
    lines = [f"# {character}", ""]
    if not latest:
        lines.append("No snapshots yet. Log in at /auth/login, then POST /api/sync.")
        return "\n".join(lines) + "\n"

    view = character_view(latest)
    who = " ".join(part for part in (view.race, view.character_class) if part)
    lines.append(f"- Level: {view.level if view.level is not None else 'unknown'}")
    if who:
        lines.append(f"- {who}" + (f", {view.specialization.name}" if view.specialization else ""))
    if view.guild:
        lines.append(f"- Guild: {view.guild}")
    if view.equipped_item_level is not None:
        lines.append(f"- Equipped item level: {view.equipped_item_level}")
    if view.captured_at:
        lines.append(f"- Data as of: {view.captured_at:%Y-%m-%d %H:%M} UTC")
    lines.append(f"- Snapshots: {', '.join(sorted(latest))}")

    if view.stats:
        s = view.stats
        lines += [
            "",
            "## Stats",
            "| Health | Armor | Defense | Str | Agi | Sta | AP | Dodge | Parry | Block | Crit |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
            "| "
            + " | ".join(
                [
                    _fmt(s.health),
                    _fmt(s.armor),
                    _fmt(s.defense),
                    _fmt(s.strength),
                    _fmt(s.agility),
                    _fmt(s.stamina),
                    _fmt(s.attack_power),
                    _fmt(s.dodge, "%"),
                    _fmt(s.parry, "%"),
                    _fmt(s.block, "%"),
                    _fmt(s.crit, "%"),
                ]
            )
            + " |",
        ]

    if view.specialization:
        spec = view.specialization
        lines += ["", f"## Talents: {spec.name} ({_fmt(spec.spent_points)} points)"]
        lines += [f"- {t.name} {_fmt(t.rank)}" for t in spec.talents]

    if view.professions:
        lines += ["", "## Professions"]
        lines += [f"- {p.name}: {_fmt(p.skill)}/{_fmt(p.max_skill)}" for p in view.professions]

    plan = gear_plan(latest, targets)
    lines += ["", "## Gear vs targets"]
    if plan.bracket_min_level is None:
        lines.append("No target bracket for this level.")
    else:
        lines += [
            f"Bracket: level {plan.bracket_min_level}+",
            "",
            "| Slot | Equipped | Target | Source |",
            "|---|---|---|---|",
        ]
        any_equipment = bool(view.equipment)
        for row in plan.rows:
            if row.equipped:
                current = ("done: " if row.reached else "") + _label(row.equipped)
            else:
                current = "empty" if any_equipment else "unknown"
            lines.append(f"| {row.slot} | {current} | {row.target.item} | {row.target.source} |")

    if plan.next_bracket_level is not None:
        lines += [
            "",
            f"Next bracket at level {plan.next_bracket_level} ({plan.next_bracket_size} targets).",
        ]

    return "\n".join(lines) + "\n"
