"""Items the character owns but doesn't wear (#186, ADR 0052).

The addon's game data lists the bags and the bank (ADR 0047). An upgrade, a gear target or a
dungeon drop that's already there is flagged "owned, not equipped", so the planner says to
go and get it rather than to earn it again. Nothing is hidden: the flag rides on the views
the app already shows.
"""

from typing import Literal

from sqlmodel import Session

from character_planner.gamedata import GameData, Items, moment, stored
from character_planner.recommend import Recommendations
from character_planner.views import GearPlan, OwnedItem, TargetInfo

type Where = Literal["bags", "bank"]


def owned_items(data: GameData | None) -> dict[int, OwnedItem]:
    """Every item in the bags and bank, by id. One in both places is in the bags: the
    nearer, and the newer snapshot (the bank's is often days old)."""
    owned: dict[int, OwnedItem] = {}
    if data is None:
        return owned
    places: tuple[tuple[Where, Items | None], ...] = (("bank", data.bank), ("bags", data.bags))
    for where, section in places:  # the bags last, so they win
        if section is None:
            continue
        counts: dict[int, int] = {}
        for item in section.items:
            counts[item.item_id] = counts.get(item.item_id, 0) + item.count
        at = moment(section.captured_at)
        for item_id, count in counts.items():
            owned[item_id] = OwnedItem(where=where, count=count, captured_at=at)
    return owned


def owned_for(session: Session, character_id: int | None) -> dict[int, OwnedItem]:
    """The character's owned items, from their newest import; none without one."""
    if character_id is None:
        return {}
    row = stored(session, character_id)
    return owned_items(GameData.model_validate(row.data) if row is not None else None)


def _of(info: TargetInfo | None, owned: dict[int, OwnedItem]) -> OwnedItem | None:
    return owned.get(info.item_id) if info is not None and info.item_id is not None else None


def mark_recommendations(rec: Recommendations, owned: dict[int, OwnedItem]) -> Recommendations:
    if not owned:
        return rec
    for row in rec.rows:
        for candidate in row.candidates:
            candidate.owned = owned.get(candidate.item.item_id)
    for dungeon in rec.dungeons:
        for upgrade in dungeon.upgrades:
            upgrade.owned = owned.get(upgrade.item.item_id)
    return rec


def mark_gear_plan(plan: GearPlan, owned: dict[int, OwnedItem]) -> GearPlan:
    """Rows whose target is owned (and not already worn: a reached target is equipped),
    and upcoming targets."""
    if not owned:
        return plan
    for row in plan.rows:
        row.owned = None if row.reached else _of(row.target_info, owned)
        for upcoming in row.upcoming:
            upcoming.owned = _of(upcoming.target_info, owned)
    for slot in plan.later:
        for upcoming in slot.upcoming:
            upcoming.owned = _of(upcoming.target_info, owned)
    return plan
