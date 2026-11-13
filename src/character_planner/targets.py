"""Gear targets edited in the app (ADR 0014, 0015).

data/curated/gear_targets.yaml is the default. Edits made on the Plan tab, and items
pinned on the Upgrades tab, are saved as a whole edited copy in the database, which wins
until it's reset. Pins are targets marked pinned, so there's one list; only pinned
targets are always listed on Upgrades.
"""

from typing import Annotated

from pydantic import BaseModel, Field
from sqlmodel import Session

from character_planner.curated import GearTarget, GearTargets
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
    level: Annotated[int, Field(ge=1, le=80)] | None = None
    priority: int | None = None
    pinned: bool = False
    item_level: int | None = None
    armor_type: str | None = None
    armor: int | None = None
    stats: dict[str, int] = {}


class EditedTargets(BaseModel):
    targets: list[EditedTarget]

    def to_targets(self) -> GearTargets:
        """Validated GearTargets; priority follows each slot's order."""
        targets: list[GearTarget] = []
        for target in self.targets:
            if target.slot not in EQUIPMENT_SLOTS:
                raise TargetsError(f"Unknown slot {target.slot}")
            fields = target.model_dump() | {"item": target.item.strip()}
            targets.append(GearTarget.model_validate(fields))
        return GearTargets(targets=targets)


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
    if source.kind == "crafted":
        return f"Crafted: {source.place}" + (f" ({source.recipe})" if source.recipe else "")
    if source.kind == "rare":
        return f"Rare: {source.place}" + (f", {source.zone}" if source.zone else "")
    if source.kind == "quest":
        return f"Quest: {source.detail} ({source.place})" if source.detail else source.place
    return f"{source.place} - {source.detail}" if source.detail else source.place


def pin_target(targets: GearTargets, item: PoolItem, slot: str) -> GearTargets:
    """Pin a pool item: mark it pinned where it's already a target, or add it as a
    pinned target at the end of its slot, at the item's own level."""
    if slot not in EQUIPMENT_SLOTS:
        raise TargetsError(f"Unknown slot {slot}")
    targets = targets.model_copy(deep=True)
    existing = [t for t in targets.targets if t.item_id == item.item_id]
    for target in existing:
        target.pinned = True
    if existing:
        return targets
    added = GearTarget(
        slot=slot,
        item=item.name,
        item_id=item.item_id,
        source="; ".join(source_text(s) for s in item.sources),
        pinned=True,
    )
    # Validate again so priority is ranked with the new target.
    return GearTargets(targets=[*targets.targets, added])


def unpin_target(targets: GearTargets, item_id: int) -> GearTargets | None:
    """Take the pin off an item; it stays a target (remove it in the editor). None when
    it isn't pinned."""
    if item_id not in targets.pinned_ids():
        return None
    targets = targets.model_copy(deep=True)
    for target in targets.targets:
        if target.item_id == item_id:
            target.pinned = False
    return targets
