"""Shipped defaults per class, chosen by the synced character's class (#80, ADR 0023).

The Warrior's defaults are the original files in data/curated/ (recommend.yaml,
stat_weights.yaml, weight_presets.yaml, gear_targets.yaml, talent_plan.yaml). Every other
class has data/curated/classes/<class>.yaml with its usage rules, weight presets, and
optionally gear targets and a talent plan; the Upgrades tuning (levels ahead, per slot,
minimum gain) is shared from recommend.yaml.

Before any sync the class isn't known, and a class without a file isn't supported yet:
both get the Warrior's defaults, as the app always did.
"""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlmodel import Session

from character_planner import fields
from character_planner.curated import GearTargets, load_gear_targets
from character_planner.db import latest_by_kind
from character_planner.recommend import UsageRules, load_rules
from character_planner.scoring import Preset, ShippedPresets, load_shipped_presets
from character_planner.talents import TalentPlan, load_default_plan
from character_planner.views import character_view

logger = logging.getLogger(__name__)

WARRIOR = "warrior"
TUNING = ("levels_ahead", "per_slot", "min_gain")


class PlayableClass(BaseModel):
    key: str  # "warlock"
    name: str  # "Warlock"


class ClassDefaults(BaseModel):
    playable: PlayableClass
    rules: UsageRules
    presets: ShippedPresets
    targets: GearTargets
    talent_plan: TalentPlan


def class_key(name: str) -> str:
    """ "Warlock" -> "warlock", "Death Knight" -> "death-knight"."""
    return "-".join(name.casefold().split())


def _class_files(curated_dir: Path) -> dict[str, Path]:
    """The class files that exist, by key. A key from outside (a guest's choice, the class
    name in a Blizzard profile) is only ever looked up here, never made into a path, so it
    can't point outside classes/."""
    return {path.stem: path for path in (curated_dir / "classes").glob("*.yaml")}


def supported_classes(curated_dir: Path) -> list[PlayableClass]:
    """Classes with shipped defaults: the Warrior, then every classes/*.yaml by name."""
    others: list[PlayableClass] = []
    for path in sorted(_class_files(curated_dir).values()):
        with path.open(encoding="utf-8") as handle:
            data = fields.as_mapping(yaml.safe_load(handle))
        others.append(PlayableClass(key=path.stem, name=str(data.get("name", path.stem.title()))))
    others.sort(key=lambda c: c.name)
    return [PlayableClass(key=WARRIOR, name="Warrior"), *others]


def load_class_defaults(curated_dir: Path, key: str) -> ClassDefaults:
    """A class's shipped defaults; the Warrior's for "warrior" or a class with no file."""
    path = _class_files(curated_dir).get(key)
    if key == WARRIOR or path is None:
        return ClassDefaults(
            playable=PlayableClass(key=WARRIOR, name="Warrior"),
            rules=load_rules(curated_dir / "recommend.yaml"),
            presets=load_shipped_presets(curated_dir),
            targets=load_gear_targets(curated_dir / "gear_targets.yaml"),
            talent_plan=load_default_plan(curated_dir / "talent_plan.yaml"),
        )

    with path.open(encoding="utf-8") as handle:
        data = fields.as_mapping(yaml.safe_load(handle))
    shared = load_rules(curated_dir / "recommend.yaml")
    rules = UsageRules.model_validate(
        {name: getattr(shared, name) for name in TUNING} | (data.get("rules") or {})
    )
    entries = [Preset.model_validate(p) for p in fields.as_list(data.get("presets"))]
    if not entries:
        raise ValueError(f"{path.name} needs at least one weight preset")
    base = entries[0].weights
    presets = [entries[0]] + [
        p.model_copy(update={"weights": base | p.weights}) for p in entries[1:]
    ]
    keys = [p.key for p in presets]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Duplicate preset keys in {path.name}: {keys}")
    plan = data.get("talent_plan")
    return ClassDefaults(
        playable=PlayableClass(key=key, name=str(data.get("name", key.title()))),
        rules=rules,
        presets=ShippedPresets(presets=presets),
        targets=GearTargets.model_validate({"targets": data.get("targets") or []}),
        talent_plan=TalentPlan.model_validate(plan) if plan else TalentPlan(spec="", steps=[]),
    )


def character_class_key(session: Session, character_id: int | None) -> str | None:
    """The synced character's class, from the latest profile; None before any sync."""
    name = character_view(latest_by_kind(session, character_id)).character_class
    return class_key(name) if name else None


def character_class_name(session: Session, character_id: int | None) -> str | None:
    """The synced character's class as Blizzard names it ("Warlock"); None before a sync."""
    return character_view(latest_by_kind(session, character_id)).character_class


def current_defaults(
    session: Session, curated_dir: Path, character_id: int | None
) -> ClassDefaults:
    """The defaults for the synced character's class (the Warrior's until it's known)."""
    key = character_class_key(session, character_id) or WARRIOR
    defaults = load_class_defaults(curated_dir, key)
    if defaults.playable.key != key:
        logger.warning("No shipped defaults for the %s class yet: using the Warrior's", key)
    return defaults
