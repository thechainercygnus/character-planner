"""Gear scoring with editable stat weights (ADR 0005).

score(item) = sum(stat value x weight) + armor x weight["Armor"] + DPS x the DPS weight
for the item's slot. Defaults live in data/curated/stat_weights.yaml; edits made in the
app are saved in the database and override them until reset.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlmodel import Session

from character_planner.db import StoredWeights, utcnow

ARMOR = "Armor"
WEAPON_DPS = "Weapon DPS"
RANGED_DPS = "Ranged DPS"


class Weights(BaseModel):
    weights: dict[str, float]

    def of(self, stat: str) -> float:
        return self.weights.get(stat, 0.0)


class WeightsView(BaseModel):
    weights: dict[str, float]
    defaults: dict[str, float]
    customised: bool


def load_default_weights(path: Path) -> Weights:
    with path.open(encoding="utf-8") as handle:
        return Weights.model_validate(yaml.safe_load(handle))


def current_weights(session: Session, defaults: Weights) -> Weights:
    stored = session.get(StoredWeights, 1)
    if stored is None or not isinstance(stored.weights, dict):
        return defaults
    # Stats added to the defaults later still get a weight.
    return Weights(weights={**defaults.weights, **stored.weights})


def save_weights(session: Session, weights: dict[str, float]) -> None:
    session.merge(StoredWeights(id=1, weights=weights, updated_at=utcnow()))
    session.commit()


def reset_weights(session: Session) -> None:
    stored = session.get(StoredWeights, 1)
    if stored is not None:
        session.delete(stored)
        session.commit()


def score(
    weights: Weights,
    *,
    slot: str,
    armor: int | None,
    stats: dict[str, int],
    dps: float | None,
) -> float:
    total = (armor or 0) * weights.of(ARMOR)
    total += sum(value * weights.of(name) for name, value in stats.items())
    if dps:
        total += dps * weights.of(RANGED_DPS if slot == "RANGED" else WEAPON_DPS)
    return round(total, 2)
