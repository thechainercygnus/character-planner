"""Gear scoring with editable stat weights (ADR 0005) in named presets (ADR 0013).

score(item) = sum(stat value x weight) + armor x weight["Armor"] + DPS x the DPS weight
for the item's slot.

Presets: "Leveling tank" is data/curated/stat_weights.yaml; weight_presets.yaml ships
more. Edits to a shipped preset are saved in the database and win until reset; presets
made in the app ("Save as") live only in the database. One preset is active and scores
everything. Stats a preset leaves out take the Leveling tank weight.
"""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import ActiveWeightPreset, StoredWeights, WeightPreset, utcnow

ARMOR = "Armor"
WEAPON_DPS = "Weapon DPS"
RANGED_DPS = "Ranged DPS"

LEVELING = "leveling-tank"
NAME_MAX = 40


class Weights(BaseModel):
    weights: dict[str, float]

    def of(self, stat: str) -> float:
        return self.weights.get(stat, 0.0)


class Preset(BaseModel):
    """A preset from the curated files."""

    key: str
    name: str
    weights: dict[str, float]


class ShippedPresets(BaseModel):
    """The curated presets, Leveling tank first."""

    presets: list[Preset]

    @property
    def base(self) -> Weights:
        return Weights(weights=self.presets[0].weights)

    def get(self, key: str) -> Preset | None:
        return next((p for p in self.presets if p.key == key), None)


class PresetSummary(BaseModel):
    key: str
    name: str
    shipped: bool  # from the curated files: can be reset, not renamed or deleted
    customised: bool  # a shipped preset with edits saved in the app


class WeightsView(BaseModel):
    """The active preset's weights, its defaults, and every preset to switch to."""

    weights: dict[str, float]
    defaults: dict[str, float]  # what "Reset" restores; a preset of your own has none
    customised: bool
    preset: str  # active preset key
    presets: list[PresetSummary]


class PresetError(ValueError):
    """A preset request that can't be done (status 400)."""


class UnknownPreset(LookupError):
    """No preset with that key (status 404)."""


def load_default_weights(path: Path) -> Weights:
    with path.open(encoding="utf-8") as handle:
        return Weights.model_validate(yaml.safe_load(handle))


def load_shipped_presets(curated_dir: Path) -> ShippedPresets:
    """stat_weights.yaml as Leveling tank, then weight_presets.yaml if it's there."""
    base = load_default_weights(curated_dir / "stat_weights.yaml")
    presets = [Preset(key=LEVELING, name="Leveling tank", weights=base.weights)]
    path = curated_dir / "weight_presets.yaml"
    if path.is_file():
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        for entry in data.get("presets", []):
            preset = Preset.model_validate(entry)
            presets.append(preset.model_copy(update={"weights": base.weights | preset.weights}))
    keys = [p.key for p in presets]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Duplicate preset keys in {path}: {keys}")
    return ShippedPresets(presets=presets)


def _stored(session: Session) -> dict[str, WeightPreset]:
    rows = session.exec(select(WeightPreset).order_by(col(WeightPreset.name))).all()
    return {row.key: row for row in rows if isinstance(row.weights, dict)}


def active_key(session: Session, shipped: ShippedPresets) -> str:
    """The active preset, or the class's first shipped preset when none is set or it
    doesn't exist for this class (Leveling tank for a Warrior, #80)."""
    default = shipped.presets[0].key
    active = session.get(ActiveWeightPreset, 1)
    if active is None:
        return default
    if shipped.get(active.key) is not None:
        return active.key
    stored = session.get(WeightPreset, active.key)
    return active.key if stored is not None and not stored.shipped else default


def _preset_weights(
    shipped: ShippedPresets, stored: dict[str, WeightPreset], key: str
) -> tuple[dict[str, float], dict[str, float] | None]:
    """(weights, defaults) for a preset; defaults is None for one made in the app."""
    preset, row = shipped.get(key), stored.get(key)
    if preset is not None:
        edits = row.weights if row is not None and row.shipped else {}
        return preset.weights | edits, preset.weights
    if row is None:
        raise UnknownPreset(key)
    # Stats added to the defaults later still get a weight.
    return shipped.base.weights | row.weights, None


def current_weights(session: Session, shipped: ShippedPresets) -> Weights:
    """The active preset's weights: what every score uses."""
    weights, _ = _preset_weights(shipped, _stored(session), active_key(session, shipped))
    return Weights(weights=weights)


def weights_view(session: Session, shipped: ShippedPresets) -> WeightsView:
    stored = _stored(session)
    key = active_key(session, shipped)
    weights, defaults = _preset_weights(shipped, stored, key)
    summaries = [
        PresetSummary(
            key=p.key,
            name=p.name,
            shipped=True,
            customised=_preset_weights(shipped, stored, p.key)[0] != p.weights,
        )
        for p in shipped.presets
    ] + [
        PresetSummary(key=row.key, name=row.name, shipped=False, customised=False)
        for row in stored.values()
        if not row.shipped and shipped.get(row.key) is None
    ]
    return WeightsView(
        weights=weights,
        defaults=defaults if defaults is not None else weights,
        customised=defaults is not None and weights != defaults,
        preset=key,
        presets=summaries,
    )


def save_weights(session: Session, shipped: ShippedPresets, weights: dict[str, float]) -> None:
    """Replace the active preset's weights."""
    key = active_key(session, shipped)
    preset = shipped.get(key)
    row = session.get(WeightPreset, key)
    name = preset.name if preset is not None else (row.name if row is not None else key)
    session.merge(
        WeightPreset(
            key=key, name=name, shipped=preset is not None, weights=weights, updated_at=utcnow()
        )
    )
    session.commit()


def reset_weights(session: Session, shipped: ShippedPresets) -> None:
    """Drop edits to the active preset, if it's a shipped one."""
    key = active_key(session, shipped)
    row = session.get(WeightPreset, key)
    if shipped.get(key) is None:
        raise PresetError("Only a shipped preset can be reset; this one is your own")
    if row is not None:
        session.delete(row)
        session.commit()


def activate(session: Session, shipped: ShippedPresets, key: str) -> None:
    if shipped.get(key) is None and key not in _custom_keys(session, shipped):
        raise UnknownPreset(key)
    session.merge(ActiveWeightPreset(id=1, key=key))
    session.commit()


def _custom_keys(session: Session, shipped: ShippedPresets) -> set[str]:
    return {k for k, row in _stored(session).items() if not row.shipped and not shipped.get(k)}


def _clean_name(session: Session, shipped: ShippedPresets, name: str, own_key: str = "") -> str:
    name = " ".join(name.split())
    if not name or len(name) > NAME_MAX:
        raise PresetError(f"Preset names must be 1-{NAME_MAX} characters")
    taken = {p.name.casefold() for p in shipped.presets} | {
        row.name.casefold() for k, row in _stored(session).items() if k != own_key
    }
    if name.casefold() in taken:
        raise PresetError(f"There's already a preset called {name}")
    return name


def create_preset(
    session: Session, shipped: ShippedPresets, name: str, weights: dict[str, float]
) -> str:
    """Save weights as a new preset of your own and make it active. Returns its key."""
    name = _clean_name(session, shipped, name)
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "preset"
    taken = {p.key for p in shipped.presets} | set(_stored(session))
    key, n = base, 2
    while key in taken:
        key, n = f"{base}-{n}", n + 1
    session.add(WeightPreset(key=key, name=name, shipped=False, weights=weights))
    session.merge(ActiveWeightPreset(id=1, key=key))
    session.commit()
    return key


def rename_preset(session: Session, shipped: ShippedPresets, key: str, name: str) -> None:
    if shipped.get(key) is not None:
        raise PresetError("Shipped presets can't be renamed; save a copy with Save as")
    row = session.get(WeightPreset, key)
    if row is None or row.shipped:
        raise UnknownPreset(key)
    row.name = _clean_name(session, shipped, name, own_key=key)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def delete_preset(session: Session, shipped: ShippedPresets, key: str) -> None:
    """Delete a preset of your own; deleting the active one goes back to Leveling tank."""
    if shipped.get(key) is not None:
        raise PresetError("Shipped presets can't be deleted; reset them instead")
    row = session.get(WeightPreset, key)
    if row is None or row.shipped:
        raise UnknownPreset(key)
    session.delete(row)
    active = session.get(ActiveWeightPreset, 1)
    if active is not None and active.key == key:
        session.delete(active)
    session.commit()


def migrate_stored_weights(session: Session) -> bool:
    """Move weights edited before presets existed into Leveling tank edits, once."""
    old = session.get(StoredWeights, 1)
    if old is None:
        return False
    if session.get(WeightPreset, LEVELING) is None and isinstance(old.weights, dict):
        session.add(
            WeightPreset(key=LEVELING, name="Leveling tank", shipped=True, weights=old.weights)
        )
    session.delete(old)
    session.commit()
    return True


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
