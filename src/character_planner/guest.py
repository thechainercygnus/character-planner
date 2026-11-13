"""Guest mode: recommendations for a class and level, without an account (ADR 0017).

Nothing here reads or writes the tracked character's data or edits: a guest picks a class,
a level, a faction and a shipped weight preset, and gets the best pool items per slot and
the dungeons worth running, as if every slot were empty. The rules and weights are the
chosen class's shipped defaults (#80, ADR 0023), never what's been edited in the app.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session

from character_planner.classes import load_class_defaults, supported_classes
from character_planner.pool import pool_view
from character_planner.recommend import Recommendations, recommend
from character_planner.scoring import Weights

Faction = Literal["alliance", "horde"]


class PresetOption(BaseModel):
    key: str
    name: str


class GuestClass(BaseModel):
    key: str
    name: str
    presets: list[PresetOption]  # this class's shipped weight presets; the first is default


class GuestOptions(BaseModel):
    """What a guest can choose from."""

    classes: list[GuestClass]  # classes with shipped defaults
    factions: list[Faction] = ["alliance", "horde"]


class GuestError(ValueError):
    """A class or preset the guest can't choose (status 422)."""


def guest_options(curated_dir: Path) -> GuestOptions:
    classes = []
    for playable in supported_classes(curated_dir):
        defaults = load_class_defaults(curated_dir, playable.key)
        classes.append(
            GuestClass(
                key=playable.key,
                name=playable.name,
                presets=[PresetOption(key=p.key, name=p.name) for p in defaults.presets.presets],
            )
        )
    return GuestOptions(classes=classes)


def guest_recommendations(
    session: Session,
    curated_dir: Path,
    *,
    class_key: str,
    level: int,
    faction: Faction,
    preset: str | None = None,
) -> Recommendations:
    """The best pool items per slot for this class and level, with every slot empty."""
    if class_key not in {c.key for c in supported_classes(curated_dir)}:
        raise GuestError(f"No defaults for the class {class_key} yet")
    defaults = load_class_defaults(curated_dir, class_key)
    chosen = defaults.presets.get(preset) if preset else defaults.presets.presets[0]
    if chosen is None:
        raise GuestError(f"No weight preset {preset} for the class {class_key}")
    return recommend(
        pool_view(session, level, faction), {}, Weights(weights=chosen.weights), defaults.rules
    )
