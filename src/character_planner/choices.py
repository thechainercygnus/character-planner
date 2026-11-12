"""Items dismissed from the Upgrades tab (ADR 0012).

recommend.yaml's exclude_item_ids stays the default; items dismissed in the app are
stored in the database and add to it. Pinned targets used to live here too; they're gear
targets now (ADR 0014), and migrate_target_choices moves old ones across.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import ItemChoice, utcnow

ChoiceKind = Literal["dismissed"]


class ItemChoiceView(BaseModel):
    item_id: int
    name: str
    choice: ChoiceKind
    created_at: datetime


class Choices(BaseModel):
    """Dismissed item ids, as the recommendation engine takes them."""

    dismissed: set[int] = set()


def list_choices(session: Session) -> list[ItemChoiceView]:
    """Every stored choice, newest first."""
    rows = session.exec(
        select(ItemChoice).order_by(col(ItemChoice.created_at).desc(), col(ItemChoice.item_id))
    ).all()
    return [
        ItemChoiceView.model_validate(r, from_attributes=True)
        for r in rows
        if r.choice == "dismissed"
    ]


def stored_choices(session: Session) -> Choices:
    return Choices(dismissed={row.item_id for row in list_choices(session)})


def set_choice(session: Session, item_id: int, name: str, choice: ChoiceKind) -> None:
    """Dismiss an item."""
    session.merge(ItemChoice(item_id=item_id, choice=choice, name=name, created_at=utcnow()))
    session.commit()


def take_target_choices(session: Session) -> list[int]:
    """Remove pins stored before ADR 0014 and return their item ids, oldest first."""
    rows = session.exec(
        select(ItemChoice)
        .where(col(ItemChoice.choice) == "target")
        .order_by(col(ItemChoice.created_at))
    ).all()
    ids = [row.item_id for row in rows]
    for row in rows:
        session.delete(row)
    session.commit()
    return ids


def clear_choice(session: Session, item_id: int) -> bool:
    """Forget the choice for an item; False when there was none."""
    row = session.get(ItemChoice, item_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
