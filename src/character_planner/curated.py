"""Gear targets: data/curated/gear_targets.yaml is the default (ADR 0014, 0015)."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator


class GearTarget(BaseModel):
    slot: str
    item: str
    source: str
    priority: int | None = None
    # Not before this level (ADR 0015): when you plan to go for it. The item's own level
    # (required level, or its quest or dungeon level) wins when it's higher or this is blank.
    level: int | None = None
    # Pinned with "Make target" on the Upgrades tab (ADR 0014): always listed there until
    # worn, whatever its rank. Targets from the YAML aren't pinned; they're only tagged.
    pinned: bool = False

    # The item's id: the reliable key for Forever Companion lookups (ADR 0004).
    item_id: int | None = None
    # Optional hand-entered item facts (from Wowhead, ForeverDB...). They override every
    # other source, so use them for corrections or items no source has.
    item_level: int | None = None
    armor_type: str | None = None  # Cloth, Leather, Mail, Plate, Shield...
    armor: int | None = None
    stats: dict[str, int] = {}

    @property
    def has_manual_data(self) -> bool:
        """Hand-entered item facts. item_id alone doesn't count: it's a lookup key."""
        return (
            self.item_level is not None
            or self.armor_type is not None
            or self.armor is not None
            or bool(self.stats)
        )


class GearTargets(BaseModel):
    """One flat list of targets (ADR 0015). Within a slot, list order is priority."""

    targets: list[GearTarget]

    @model_validator(mode="before")
    @classmethod
    def _from_brackets(cls, data: Any) -> Any:
        """Read targets saved in level brackets (ADR 0014): each target takes its
        bracket's level as its own, and a slot keeps bracket order, then priority."""
        if not isinstance(data, dict) or "brackets" not in data or "targets" in data:
            return data
        brackets = sorted(data["brackets"], key=lambda b: b.get("min_level", 0))
        targets = []
        for bracket in brackets:
            ranked = sorted(
                bracket.get("targets", []),
                key=lambda t: (t.get("priority") is None, t.get("priority") or 0),
            )
            for target in ranked:
                targets.append({"level": bracket.get("min_level"), **target})
        return {"targets": targets}

    @model_validator(mode="after")
    def _rank(self) -> GearTargets:
        """Priority is a target's position among its slot's targets, from 1."""
        seen: dict[str, int] = {}
        for target in self.targets:
            seen[target.slot] = seen.get(target.slot, 0) + 1
            target.priority = seen[target.slot]
        return self

    def for_slot(self, slot: str) -> list[GearTarget]:
        """A slot's targets in priority order."""
        return [t for t in self.targets if t.slot == slot]

    def slots(self) -> list[str]:
        """Slots with targets, in order of first appearance."""
        return list(dict.fromkeys(t.slot for t in self.targets))

    def item_ids(self) -> list[int]:
        """Hand-entered item ids, deduplicated."""
        return list(dict.fromkeys(t.item_id for t in self.targets if t.item_id is not None))

    def pinned_ids(self) -> set[int]:
        """Item ids of pinned targets."""
        return {t.item_id for t in self.targets if t.pinned and t.item_id is not None}

    def item_names(self) -> list[str]:
        """Every target item name, deduplicated, in list order."""
        return list(dict.fromkeys(t.item for t in self.targets))


def load_gear_targets(path: Path) -> GearTargets:
    with path.open(encoding="utf-8") as handle:
        return GearTargets.model_validate(yaml.safe_load(handle))
