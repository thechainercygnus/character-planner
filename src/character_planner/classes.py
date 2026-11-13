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


def _class_file(curated_dir: Path, key: str) -> Path:
    return curated_dir / "classes" / f"{key}.yaml"


def supported_classes(curated_dir: Path) -> list[PlayableClass]:
    """Classes with shipped defaults: the Warrior, then every classes/*.yaml by name."""
    others = []
    for path in sorted((curated_dir / "classes").glob("*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        others.append(PlayableClass(key=path.stem, name=str(data.get("name", path.stem.title()))))
    others.sort(key=lambda c: c.name)
    return [PlayableClass(key=WARRIOR, name="Warrior"), *others]


def load_class_defaults(curated_dir: Path, key: str) -> ClassDefaults:
    """A class's shipped defaults; the Warrior's for "warrior" or a class with no file."""
    path = _class_file(curated_dir, key)
    if key == WARRIOR or not path.is_file():
        return ClassDefaults(
            playable=PlayableClass(key=WARRIOR, name="Warrior"),
            rules=load_rules(curated_dir / "recommend.yaml"),
            presets=load_shipped_presets(curated_dir),
            targets=load_gear_targets(curated_dir / "gear_targets.yaml"),
            talent_plan=load_default_plan(curated_dir / "talent_plan.yaml"),
        )

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    shared = load_rules(curated_dir / "recommend.yaml")
    rules = UsageRules.model_validate(
        {name: getattr(shared, name) for name in TUNING} | (data.get("rules") or {})
    )
    entries = [Preset.model_validate(p) for p in data.get("presets") or []]
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


def character_class_key(session: Session) -> str | None:
    """The synced character's class, from the latest profile; None before any sync."""
    name = character_view(latest_by_kind(session)).character_class
    return class_key(name) if name else None


def current_defaults(session: Session, curated_dir: Path) -> ClassDefaults:
    """The defaults for the synced character's class (the Warrior's until it's known)."""
    key = character_class_key(session) or WARRIOR
    defaults = load_class_defaults(curated_dir, key)
    if defaults.playable.key != key:
        logger.warning("No shipped defaults for the %s class yet: using the Warrior's", key)
    return defaults
