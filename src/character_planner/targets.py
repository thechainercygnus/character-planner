"""Gear targets edited in the app (ADR 0014).

data/curated/gear_targets.yaml is the default. Edits made on the Plan tab, and items
pinned on the Upgrades tab, are saved as a whole edited copy in the database, which wins
until it's reset. Pins go into the bracket for the character's level, so there's one list.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from sqlmodel import Session

from character_planner.curated import Bracket, GearTarget, GearTargets
from character_planner.db import StoredGearTargets, utcnow
from character_planner.pool import PoolItem, PoolSource
from character_planner.recommend import EQUIPMENT_SLOTS


class TargetsError(ValueError):
    """Targets that can't be saved (status 422)."""


class EditedTarget(BaseModel):
    """A target as the editor sends it: bounded text, the rest as in GearTarget."""

    slot: str
    item: Annotated[str, Field(min_length=1, max_length=120)]
    source: Annotated[str, Field(max_length=200)] = ""
    item_id: Annotated[int, Field(gt=0)] | None = None
    priority: int | None = None
    item_level: int | None = None
    armor_type: str | None = None
    armor: int | None = None
    stats: dict[str, int] = {}


class EditedBracket(BaseModel):
    min_level: Annotated[int, Field(ge=1, le=80)]
    targets: list[EditedTarget]


class EditedTargets(BaseModel):
    brackets: list[EditedBracket]

    def to_targets(self) -> GearTargets:
        """Validated GearTargets, brackets by level and priority by position."""
        levels = [b.min_level for b in self.brackets]
        if len(set(levels)) != len(levels):
            raise TargetsError("Each bracket needs its own level")
        brackets = []
        for bracket in sorted(self.brackets, key=lambda b: b.min_level):
            targets = []
            for position, target in enumerate(bracket.targets, start=1):
                if target.slot not in EQUIPMENT_SLOTS:
                    raise TargetsError(f"Unknown slot {target.slot}")
                fields = target.model_dump() | {"item": target.item.strip(), "priority": position}
                targets.append(GearTarget.model_validate(fields))
            brackets.append(Bracket(min_level=bracket.min_level, targets=targets))
        return GearTargets(brackets=brackets)


def current_targets(session: Session, default: GearTargets) -> GearTargets:
    stored = session.get(StoredGearTargets, 1)
    if stored is None:
        return default
    return GearTargets.model_validate(stored.targets)


def is_customised(session: Session) -> bool:
    return session.get(StoredGearTargets, 1) is not None


def save_targets(session: Session, targets: GearTargets) -> None:
    session.merge(
        StoredGearTargets(id=1, targets=targets.model_dump(exclude_none=True), updated_at=utcnow())
    )
    session.commit()


def reset_targets(session: Session) -> None:
    stored = session.get(StoredGearTargets, 1)
    if stored is not None:
        session.delete(stored)
        session.commit()


def source_text(source: PoolSource) -> str:
    """A pool source in gear_targets.yaml's style."""
    if source.kind == "quest":
        return f"Quest: {source.detail} ({source.dungeon})" if source.detail else source.dungeon
    return f"{source.dungeon} - {source.detail}" if source.detail else source.dungeon


def _bracket_for(targets: GearTargets, level: int | None) -> int:
    """Index of the bracket a pin goes into, adding one at the level when none fits."""
    floor = level or 1
    eligible = [i for i, b in enumerate(targets.brackets) if b.min_level <= floor]
    if eligible:
        return max(eligible, key=lambda i: targets.brackets[i].min_level)
    targets.brackets.append(Bracket(min_level=floor, targets=[]))
    targets.brackets.sort(key=lambda b: b.min_level)
    return next(i for i, b in enumerate(targets.brackets) if b.min_level == floor)


def pin_target(targets: GearTargets, item: PoolItem, slot: str, level: int | None) -> GearTargets:
    """Add a pool item to the current bracket. Already there: unchanged."""
    if slot not in EQUIPMENT_SLOTS:
        raise TargetsError(f"Unknown slot {slot}")
    targets = targets.model_copy(deep=True)
    bracket = targets.brackets[_bracket_for(targets, level)]
    if any(t.item_id == item.item_id for t in bracket.targets):
        return targets
    bracket.targets.append(
        GearTarget(
            slot=slot,
            item=item.name,
            item_id=item.item_id,
            source="; ".join(source_text(s) for s in item.sources),
            priority=len(bracket.targets) + 1,
        )
    )
    return targets


def unpin_target(targets: GearTargets, item_id: int, level: int | None) -> GearTargets | None:
    """Remove an item from the current bracket; None when it isn't there."""
    current = targets.for_level(level or 1)
    if current is None or not any(t.item_id == item_id for t in current.targets):
        return None
    brackets = [
        b.model_copy(update={"targets": [t for t in b.targets if t.item_id != item_id]})
        if b.min_level == current.min_level
        else b
        for b in targets.brackets
    ]
    return GearTargets(brackets=brackets)


def pinned_ids(targets: GearTargets, level: int | None) -> set[int]:
    """Targets for the character's level: always listed on the Upgrades tab."""
    current = targets.for_level(level) if level is not None else None
    return {t.item_id for t in current.targets if t.item_id is not None} if current else set()
