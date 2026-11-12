"""Hand-curated planning data (gear targets) kept as YAML in data/curated/."""

from pathlib import Path

import yaml
from pydantic import BaseModel


class GearTarget(BaseModel):
    slot: str
    item: str
    source: str
    priority: int | None = None
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


class Bracket(BaseModel):
    min_level: int
    targets: list[GearTarget]


class GearTargets(BaseModel):
    brackets: list[Bracket]

    def for_level(self, level: int) -> Bracket | None:
        """The highest bracket at or below the level: what to chase right now."""
        eligible = [b for b in self.brackets if b.min_level <= level]
        return max(eligible, key=lambda b: b.min_level, default=None)

    def next_after(self, level: int) -> Bracket | None:
        upcoming = [b for b in self.brackets if b.min_level > level]
        return min(upcoming, key=lambda b: b.min_level, default=None)

    def item_ids(self) -> list[int]:
        """Hand-entered item ids across all brackets, deduplicated."""
        ids = (t.item_id for b in self.brackets for t in b.targets if t.item_id is not None)
        return list(dict.fromkeys(ids))

    def pinned_ids(self) -> set[int]:
        """Item ids of pinned targets, in any bracket."""
        return {
            t.item_id
            for b in self.brackets
            for t in b.targets
            if t.pinned and t.item_id is not None
        }

    def item_names(self) -> list[str]:
        """Every target item name across all brackets, deduplicated, in file order."""
        return list(dict.fromkeys(t.item for b in self.brackets for t in b.targets))


def load_gear_targets(path: Path) -> GearTargets:
    with path.open(encoding="utf-8") as handle:
        return GearTargets.model_validate(yaml.safe_load(handle))
