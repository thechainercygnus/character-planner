"""Corrections to the enchant reference data, made in the app (#36, ADR 0033).

data/curated/enchants.yaml stays the default: a material's level, a crafted enchant's
effect and how many enchants to list per slot. A correction replaces one value and can
be reset to the shipped one. Values never corrected keep following the YAML, so a
release with better bands still reaches them.

Stored as one JSON row, like the Upgrades rules (ADR 0016).
"""

from pydantic import BaseModel, Field
from sqlmodel import Session

from character_planner.db import StoredEnchantCorrections, utcnow
from character_planner.enchants import EFFECT_NAMES, EnchantData

MAX_LEVEL = 60
MAX_PER_SLOT = 10


class CorrectionError(ValueError):
    pass


class EnchantCorrections(BaseModel):
    reagent_levels: dict[int, int] = {}
    crafted_effects: dict[int, dict[str, float]] = {}
    per_slot: int | None = None


class EffectsUpdate(BaseModel):
    effects: dict[str, float] = Field(min_length=1)


class LevelUpdate(BaseModel):
    level: int = Field(ge=1, le=MAX_LEVEL)


class PerSlotUpdate(BaseModel):
    per_slot: int = Field(ge=1, le=MAX_PER_SLOT)


class CorrectionsView(BaseModel):
    """What's corrected, what ships, and the effect names a correction may use."""

    corrections: EnchantCorrections
    shipped: EnchantData
    effect_names: list[str]


def stored_corrections(session: Session) -> EnchantCorrections:
    row = session.get(StoredEnchantCorrections, 1)
    return EnchantCorrections.model_validate(row.corrections) if row else EnchantCorrections()


def apply(shipped: EnchantData, corrections: EnchantCorrections) -> EnchantData:
    """The shipped data with each correction on top, marked as corrected."""
    return shipped.model_copy(
        update={
            "reagent_levels": {**shipped.reagent_levels, **corrections.reagent_levels},
            "crafted_effects": {**shipped.crafted_effects, **corrections.crafted_effects},
            "per_slot": corrections.per_slot or shipped.per_slot,
            "corrected_reagents": set(corrections.reagent_levels),
            "corrected_crafted": set(corrections.crafted_effects),
            "per_slot_corrected": corrections.per_slot is not None,
        }
    )


def corrections_view(session: Session, shipped: EnchantData) -> CorrectionsView:
    return CorrectionsView(
        corrections=stored_corrections(session),
        shipped=shipped,
        effect_names=list(EFFECT_NAMES),
    )


def _save(session: Session, corrections: EnchantCorrections) -> None:
    row = session.get(StoredEnchantCorrections, 1)
    data = corrections.model_dump(mode="json")
    if row is None:
        session.add(StoredEnchantCorrections(id=1, corrections=data))
    else:
        row.corrections = data
        row.updated_at = utcnow()
        session.add(row)
    session.commit()


def set_reagent_level(session: Session, item_id: int, level: int) -> None:
    corrections = stored_corrections(session)
    corrections.reagent_levels[item_id] = level
    _save(session, corrections)


def set_crafted_effects(session: Session, item_id: int, effects: dict[str, float]) -> None:
    unknown = sorted(name for name in effects if name not in EFFECT_NAMES)
    if unknown:
        raise CorrectionError(f"Unknown effect: {', '.join(unknown)}")
    if any(value <= 0 for value in effects.values()):
        raise CorrectionError("Effects must be above 0")
    corrections = stored_corrections(session)
    corrections.crafted_effects[item_id] = dict(effects)
    _save(session, corrections)


def set_per_slot(session: Session, per_slot: int) -> None:
    corrections = stored_corrections(session)
    corrections.per_slot = per_slot
    _save(session, corrections)


def reset_reagent_level(session: Session, item_id: int) -> bool:
    corrections = stored_corrections(session)
    if corrections.reagent_levels.pop(item_id, None) is None:
        return False
    _save(session, corrections)
    return True


def reset_crafted_effects(session: Session, item_id: int) -> bool:
    corrections = stored_corrections(session)
    if corrections.crafted_effects.pop(item_id, None) is None:
        return False
    _save(session, corrections)
    return True


def reset_per_slot(session: Session) -> bool:
    corrections = stored_corrections(session)
    if corrections.per_slot is None:
        return False
    corrections.per_slot = None
    _save(session, corrections)
    return True
