"""Progress over time, rebuilt from the stored snapshots (ADR 0002, ADR 0008).

Every sync stores one snapshot per endpoint, a few milliseconds apart. Snapshots within
SYNC_GAP of each other form one sync; each sync becomes a point (level, item level, gear
score, health, armor, stamina). Comparing consecutive syncs gives the gear changes and
level-ups. Nothing new is stored: history is whatever has been synced.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import Snapshot
from character_planner.scoring import Weights, score
from character_planner.views import (
    GEAR_SLOTS,
    EquippedItem,
    average_item_level,
    character_level,
    parse_equipment,
    parse_stats,
)

SYNC_GAP = timedelta(seconds=30)
TRACKED_KINDS = ("profile", "equipment", "statistics")


class ProgressPoint(BaseModel):
    captured_at: datetime
    level: int | None = None
    item_level: float | None = None
    # Sum of the equipped items' scores with the current stat weights, so it moves with
    # gear swaps and with weight changes alike.
    gear_score: float | None = None
    health: int | None = None
    armor: int | None = None
    stamina: int | None = None


class GearChange(BaseModel):
    captured_at: datetime
    slot: str
    before: str | None  # None: the slot was empty
    after: str | None  # None: the item was taken off
    item_level_before: int | None = None
    item_level_after: int | None = None
    score_change: float


class LevelUp(BaseModel):
    captured_at: datetime
    level: int


class Progress(BaseModel):
    points: list[ProgressPoint]
    gear_changes: list[GearChange]  # newest first
    level_ups: list[LevelUp]  # newest first


def item_score(weights: Weights, item: EquippedItem | None) -> float:
    if item is None:
        return 0.0
    stats = {s.name: s.value for s in item.stats}
    return score(weights, slot=item.slot, armor=item.armor, stats=stats, dps=item.dps)


def sync_batches(snapshots: Iterable[Snapshot]) -> list[dict[str, Snapshot]]:
    """Group snapshots (oldest first) into syncs: runs no more than SYNC_GAP apart."""
    batches: list[dict[str, Snapshot]] = []
    last: datetime | None = None
    for snap in sorted(snapshots, key=lambda s: (s.captured_at, s.id or 0)):
        if last is None or snap.captured_at - last > SYNC_GAP:
            batches.append({})
        batches[-1][snap.kind] = snap
        last = snap.captured_at
    return batches


def _payload(state: Mapping[str, Snapshot], kind: str) -> Any:
    snap = state.get(kind)
    return snap.payload if snap else None


def build_progress(snapshots: Iterable[Snapshot], weights: Weights) -> Progress:
    """Points, gear changes and level-ups from successful snapshots, any order."""
    points: list[ProgressPoint] = []
    changes: list[GearChange] = []
    level_ups: list[LevelUp] = []

    # A sync that misses a kind (or a manual snapshot of one kind) keeps the last one.
    state: dict[str, Snapshot] = {}
    previous_gear: dict[str, EquippedItem] | None = None
    previous_level: int | None = None
    for batch in sync_batches(snapshots):
        state.update(batch)
        moment = max(s.captured_at for s in batch.values())
        equipment = parse_equipment(_payload(state, "equipment"))
        gear = {i.slot: i for i in equipment if i.slot in GEAR_SLOTS}
        stats = parse_stats(_payload(state, "statistics"))
        level = character_level(_payload(state, "profile"))

        points.append(
            ProgressPoint(
                captured_at=moment,
                level=level,
                item_level=average_item_level(equipment),
                gear_score=(
                    round(sum(item_score(weights, i) for i in gear.values()), 2)
                    if "equipment" in state
                    else None
                ),
                health=stats.health if stats else None,
                armor=stats.armor if stats else None,
                stamina=stats.stamina if stats else None,
            )
        )

        if previous_gear is not None and "equipment" in batch:
            for slot in sorted(set(previous_gear) | set(gear)):
                old, new = previous_gear.get(slot), gear.get(slot)
                if (old.item_id if old else None) == (new.item_id if new else None):
                    continue
                changes.append(
                    GearChange(
                        captured_at=moment,
                        slot=slot,
                        before=old.name if old else None,
                        after=new.name if new else None,
                        item_level_before=old.item_level if old else None,
                        item_level_after=new.item_level if new else None,
                        score_change=round(item_score(weights, new) - item_score(weights, old), 2),
                    )
                )
        if "equipment" in state:
            previous_gear = gear

        if level is not None and previous_level is not None and level > previous_level:
            level_ups.append(LevelUp(captured_at=moment, level=level))
        previous_level = level if level is not None else previous_level

    changes.sort(key=lambda c: c.captured_at, reverse=True)
    level_ups.sort(key=lambda u: u.captured_at, reverse=True)
    return Progress(points=points, gear_changes=changes, level_ups=level_ups)


def progress(session: Session, weights: Weights) -> Progress:
    rows = session.exec(
        select(Snapshot).where(
            col(Snapshot.kind).in_(TRACKED_KINDS),
            col(Snapshot.status) >= 200,
            col(Snapshot.status) < 300,
        )
    ).all()
    return build_progress(rows, weights)
