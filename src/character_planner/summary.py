"""Markdown character summary, for pasting into a Claude chat.

Forever responses use the retail Profile API shapes (level on the profile,
equipped_items[].slot.type on equipment), confirmed by the 2026-11-11 spike; see
tests/fixtures/forever_*.json. Reads stay defensive because the API is undocumented
and can change: a missing field shows as unknown instead of failing the summary.
"""

from collections.abc import Mapping
from typing import Any

from character_planner.curated import GearTargets
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


def character_level(profile: Any) -> int | None:
    level = _get(profile, "level")
    return level if isinstance(level, int) else None


def equipped_by_slot(equipment: Any) -> dict[str, str]:
    items = _get(equipment, "equipped_items") or []
    equipped: dict[str, str] = {}
    for item in items:
        slot = _get(item, "slot", "type")
        name = _name(_get(item, "name"))
        quality = _name(_get(item, "quality", "name"))
        if slot and name:
            equipped[slot] = f"{name} ({quality})" if quality else name
    return equipped


def build_summary(
    character: str,
    latest: Mapping[str, Snapshot],
    targets: GearTargets,
) -> str:
    profile = latest.get("profile")
    equipment = latest.get("equipment")
    level = character_level(profile.payload) if profile else None

    lines = [f"# {character}", ""]
    if not latest:
        lines.append("No snapshots yet. Log in at /auth/login, then POST /sync.")
        return "\n".join(lines) + "\n"

    newest = max(s.captured_at for s in latest.values())
    lines.append(f"- Level: {level if level is not None else 'unknown'}")
    lines.append(f"- Data as of: {newest:%Y-%m-%d %H:%M} UTC")
    lines.append(f"- Snapshots: {', '.join(sorted(latest))}")
    lines.append("")

    equipped = equipped_by_slot(equipment.payload) if equipment else {}
    bracket = targets.for_level(level) if level is not None else None

    lines.append("## Gear vs targets")
    if bracket is None:
        lines.append("No target bracket for this level.")
    else:
        lines.append(f"Bracket: level {bracket.min_level}+")
        lines.append("")
        lines.append("| Slot | Equipped | Target | Source |")
        lines.append("|---|---|---|---|")
        ordered = sorted(bracket.targets, key=lambda t: (t.priority is None, t.priority or 0))
        for target in ordered:
            current = equipped.get(target.slot, "unknown" if not equipped else "empty")
            done = "done: " if target.item in current else ""
            lines.append(f"| {target.slot} | {done}{current} | {target.item} | {target.source} |")

    upcoming = targets.next_after(level) if level is not None else None
    if upcoming:
        lines.append("")
        lines.append(
            f"Next bracket at level {upcoming.min_level} ({len(upcoming.targets)} targets)."
        )

    return "\n".join(lines) + "\n"
