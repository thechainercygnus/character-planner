"""Hand-curated planning data (gear targets) kept as YAML in data/curated/."""

from pathlib import Path

import yaml
from pydantic import BaseModel


class GearTarget(BaseModel):
    slot: str
    item: str
    source: str
    priority: int | None = None

    # Optional hand-entered item data (from Wowhead, ForeverDB...). Used when the
    # Battle.net item search can't find the item, as happens for Forever-new items.
    item_id: int | None = None
    item_level: int | None = None
    armor_type: str | None = None  # Cloth, Leather, Mail, Plate, Shield...
    armor: int | None = None
    stats: dict[str, int] = {}

    @property
    def has_manual_data(self) -> bool:
        return any(
            value is not None for value in (self.item_id, self.item_level, self.armor_type)
        ) or bool(self.armor is not None or self.stats)


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

    def item_names(self) -> list[str]:
        """Every target item name across all brackets, deduplicated, in file order."""
        return list(dict.fromkeys(t.item for b in self.brackets for t in b.targets))


def load_gear_targets(path: Path) -> GearTargets:
    with path.open(encoding="utf-8") as handle:
        return GearTargets.model_validate(yaml.safe_load(handle))
