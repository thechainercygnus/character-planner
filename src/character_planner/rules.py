"""The Upgrades rules edited in the app (ADR 0016).

data/curated/recommend.yaml is the default: what the character can wear (weapon, armor
and off-hand types, plate level, two-handers) and how the Upgrades tab lists items (levels
ahead, per slot, minimum gain). Edits are saved as a whole edited copy in the database,
which wins until it's reset, as weights, the talent plan and targets do.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from sqlmodel import Session

from character_planner.db import StoredUsageRules, utcnow
from character_planner.recommend import UsageRules

# The choices the editor offers. Values as Forever Companion's item details spell them
# (weaponType, armor class), seen in the item pool on 2026-11-12; Shield is the weapon
# type of shields. Held-in-off-hand items have the weapon type Miscellaneous.
WEAPON_TYPES = [
    "Axe",
    "Mace",
    "Sword",
    "Dagger",
    "Fist Weapon",
    "Polearm",
    "Staff",
    "Bow",
    "Crossbow",
    "Gun",
    "Thrown",
    "Wand",
    "Shield",
]
ARMOR_TYPES = ["cloth", "leather", "mail"]  # plate comes from plate_from_level
OFF_HAND_TYPES = ["Shield", "Miscellaneous", "Axe", "Mace", "Sword", "Dagger", "Fist Weapon"]
# Weapon types seen on Two-Hand items in the pool (2026-11-12).
TWO_HAND_TYPES = ["Axe", "Mace", "Polearm", "Staff", "Sword"]


class RulesError(ValueError):
    """Rules that can't be saved (status 422)."""


class EditedRules(BaseModel):
    """Rules as the editor sends them, bounded."""

    weapon_types: list[str]
    armor_types: list[str]
    plate_from_level: Annotated[int, Field(ge=1, le=80)] | None = None
    mail_from_level: Annotated[int, Field(ge=1, le=80)] | None = None
    two_handers: bool = False
    two_hand_types: list[str] | None = None  # None: any weapon type
    off_hand_types: list[str]
    levels_ahead: Annotated[int, Field(ge=0, le=20)]
    per_slot: Annotated[int, Field(ge=1, le=10)]
    min_gain: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]

    def to_rules(self) -> UsageRules:
        """Validated UsageRules, with each list in the editor's order and no repeats."""
        lists = {
            "weapon_types": (self.weapon_types, WEAPON_TYPES),
            "armor_types": (self.armor_types, ARMOR_TYPES),
            "off_hand_types": (self.off_hand_types, OFF_HAND_TYPES),
        }
        if self.two_hand_types is not None:
            lists["two_hand_types"] = (self.two_hand_types, TWO_HAND_TYPES)
        cleaned: dict[str, list[str]] = {}
        for name, (values, known) in lists.items():
            unknown = sorted(set(values) - set(known))
            if unknown:
                raise RulesError(f"Unknown {name.replace('_', ' ')}: {', '.join(unknown)}")
            cleaned[name] = [value for value in known if value in values]
        return UsageRules.model_validate(self.model_dump() | cleaned)


class RulesView(BaseModel):
    rules: UsageRules
    defaults: UsageRules
    customised: bool
    # What the editor can offer.
    weapon_type_options: list[str] = WEAPON_TYPES
    armor_type_options: list[str] = ARMOR_TYPES
    off_hand_type_options: list[str] = OFF_HAND_TYPES
    two_hand_type_options: list[str] = TWO_HAND_TYPES


def current_rules(session: Session, default: UsageRules) -> UsageRules:
    stored = session.get(StoredUsageRules, 1)
    if stored is None:
        return default
    return UsageRules.model_validate(stored.rules)


def rules_view(session: Session, default: UsageRules) -> RulesView:
    return RulesView(
        rules=current_rules(session, default),
        defaults=default,
        customised=session.get(StoredUsageRules, 1) is not None,
    )


def save_rules(session: Session, rules: UsageRules) -> None:
    session.merge(StoredUsageRules(id=1, rules=rules.model_dump(), updated_at=utcnow()))
    session.commit()


def reset_rules(session: Session) -> None:
    stored = session.get(StoredUsageRules, 1)
    if stored is not None:
        session.delete(stored)
        session.commit()
