"""Hand-curated planning data (gear targets) kept as YAML in data/curated/."""

from pathlib import Path

import yaml
from pydantic import BaseModel


class GearTarget(BaseModel):
    slot: str
    item: str
    source: str
    priority: int | None = None


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


def load_gear_targets(path: Path) -> GearTargets:
    with path.open(encoding="utf-8") as handle:
        return GearTargets.model_validate(yaml.safe_load(handle))
