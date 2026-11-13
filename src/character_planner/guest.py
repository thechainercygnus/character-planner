"""Guest mode: recommendations for a class and level, without an account (ADR 0017).

Nothing here reads or writes the tracked character's data or edits: a guest picks a class,
a level, a faction and a shipped weight preset, and gets the best pool items per slot and
the dungeons worth running, as if every slot were empty. The rules are the shipped
recommend.yaml and the weights a shipped preset, never what's been edited in the app.
"""

from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session

from character_planner.pool import pool_view
from character_planner.recommend import Recommendations, UsageRules, recommend
from character_planner.scoring import ShippedPresets, Weights

Faction = Literal["alliance", "horde"]


class GuestClass(BaseModel):
    key: str
    name: str


# Classes with shipped rules. Only the Warrior's exist until #15 adds rules for every class.
GUEST_CLASSES = [GuestClass(key="warrior", name="Warrior")]


class PresetOption(BaseModel):
    key: str
    name: str


class GuestOptions(BaseModel):
    """What a guest can choose from."""

    classes: list[GuestClass]
    presets: list[PresetOption]  # shipped weight presets, the first is the default
    factions: list[Faction] = ["alliance", "horde"]


class GuestError(ValueError):
    """A class or preset the guest can't choose (status 422)."""


def guest_options(presets: ShippedPresets) -> GuestOptions:
    return GuestOptions(
        classes=GUEST_CLASSES,
        presets=[PresetOption(key=p.key, name=p.name) for p in presets.presets],
    )


def guest_recommendations(
    session: Session,
    rules: UsageRules,
    presets: ShippedPresets,
    *,
    class_key: str,
    level: int,
    faction: Faction,
    preset: str | None = None,
) -> Recommendations:
    """The best pool items per slot for this class and level, with every slot empty."""
    if class_key not in {c.key for c in GUEST_CLASSES}:
        raise GuestError(f"No rules for the class {class_key} yet")
    chosen = presets.get(preset) if preset else presets.presets[0]
    if chosen is None:
        raise GuestError(f"No weight preset {preset}")
    return recommend(pool_view(session, level, faction), {}, Weights(weights=chosen.weights), rules)
