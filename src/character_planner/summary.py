"""Markdown character summary, for pasting into a Claude chat.

Rendering only: all parsing of API responses lives in views.py.
"""

from collections.abc import Mapping
from typing import Any

from character_planner.companion import CompanionInfo
from character_planner.curated import GearTargets
from character_planner.db import CatalogItem, Snapshot
from character_planner.scoring import Weights
from character_planner.views import (
    GEAR_SLOTS,
    EquippedItem,
    GearRow,
    UpcomingTarget,
    character_level,
    character_view,
    gear_plan,
    parse_equipment,
)

__all__ = ["build_summary", "character_level", "equipped_by_slot"]


def _upcoming(upcoming: list[UpcomingTarget]) -> str:
    """Targets coming up in a slot, nearest first."""
    parts = [
        f"{u.target.item} (level {u.level})" if u.level is not None else u.target.item
        for u in upcoming
    ]
    return "; ".join(parts) or "-"


def _label(item: EquippedItem) -> str:
    return f"{item.name} ({item.quality_name})" if item.quality_name else item.name


def equipped_by_slot(equipment: Any) -> dict[str, str]:
    return {item.slot: _label(item) for item in parse_equipment(equipment)}


def _verdict(row: GearRow) -> str:
    if row.verdict == "reached":
        return "reached"
    # What's worn scores higher: the target is outgrown, but stays until worn (ADR 0015).
    text = "outgrown" if row.verdict == "downgrade" else row.verdict
    info = row.target_info
    details = []
    if row.equipped and row.equipped.item_level is not None and info and info.item_level:
        details.append(f"ilvl {row.equipped.item_level} -> {info.item_level}")
    if row.score_delta is not None:
        details.append(f"score {row.score_delta:+.1f}")
    if details:
        text += f" ({', '.join(details)})"
    gains = []
    if row.armor_delta:
        gains.append(f"{row.armor_delta:+d} armor")
    gains += [f"{change:+d} {name}" for name, change in row.stat_deltas.items()]
    if gains:
        text += f"; {', '.join(gains)}"
    if info:
        text += f" [{'+'.join(info.sources)}]"
    if row.warning:
        text += f"; {row.warning}"
    return text


def _fmt(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "?"
    return f"{value:.1f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def build_summary(
    character: str,
    latest: Mapping[str, Snapshot],
    targets: GearTargets,
    catalog: Mapping[str, CatalogItem] | None = None,
    icons: Mapping[int, str] | None = None,
    companion: Mapping[int, CompanionInfo] | None = None,
    weights: Weights | None = None,
    item_levels: Mapping[int, int] | None = None,
) -> str:
    lines = [f"# {character}", ""]
    if not latest:
        lines.append("No snapshots yet. Log in at /auth/login, then POST /api/sync.")
        return "\n".join(lines) + "\n"

    view = character_view(latest, icons)
    who = " ".join(part for part in (view.race, view.character_class) if part)
    lines.append(f"- Level: {view.level if view.level is not None else 'unknown'}")
    if who:
        lines.append(f"- {who}" + (f", {view.specialization.name}" if view.specialization else ""))
    if view.guild:
        lines.append(f"- Guild: {view.guild}")
    if view.equipped_item_level is not None:
        lines.append(
            f"- Equipped item level: {view.equipped_item_level} "
            f"({view.gear_slots_filled}/{len(GEAR_SLOTS)} slots filled)"
        )
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

    plan = gear_plan(latest, targets, catalog, icons, companion, weights, item_levels)
    lines += ["", "## Gear vs targets"]
    if not plan.rows and not plan.later:
        lines.append("No gear targets yet.")
    if plan.rows:
        lines += [
            "",
            "| Slot | Equipped | Target now | Source | Verdict | Coming up |",
            "|---|---|---|---|---|---|",
        ]
        any_equipment = bool(view.equipment)
        for row in plan.rows:
            if row.equipped:
                current = ("done: " if row.reached else "") + _label(row.equipped)
            else:
                current = "empty" if any_equipment else "unknown"
            lines.append(
                f"| {row.slot} | {current} | {row.target.item} | {row.target.source} "
                f"| {_verdict(row)} | {_upcoming(row.upcoming)} |"
            )
    if plan.later:
        lines += ["", "Coming up in other slots:"]
        lines += [f"- {slot.slot}: {_upcoming(slot.upcoming)}" for slot in plan.later]

    for credit in plan.attributions:
        lines += ["", f"_{credit['text']} {credit['url']}_"]

    return "\n".join(lines) + "\n"
