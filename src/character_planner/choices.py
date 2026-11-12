"""Items pinned as targets or dismissed from the Upgrades tab (ADR 0012).

The curated files stay the defaults: gear_targets.yaml names targets and
recommend.yaml's exclude_item_ids hides items. Choices made in the app are stored in
the database and add to both.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import ItemChoice, utcnow

ChoiceKind = Literal["target", "dismissed"]


class ItemChoiceView(BaseModel):
    item_id: int
    name: str
    choice: ChoiceKind
    created_at: datetime


class Choices(BaseModel):
    """Item ids by choice, as the recommendation engine takes them."""

    targets: set[int] = set()
    dismissed: set[int] = set()


def list_choices(session: Session) -> list[ItemChoiceView]:
    """Every stored choice, newest first."""
    rows = session.exec(
        select(ItemChoice).order_by(col(ItemChoice.created_at).desc(), col(ItemChoice.item_id))
    ).all()
    return [
        ItemChoiceView.model_validate(r, from_attributes=True)
        for r in rows
        if r.choice in ("target", "dismissed")
    ]


def stored_choices(session: Session) -> Choices:
    choices = Choices()
    for row in list_choices(session):
        (choices.targets if row.choice == "target" else choices.dismissed).add(row.item_id)
    return choices


def set_choice(session: Session, item_id: int, name: str, choice: ChoiceKind) -> None:
    """Pin or dismiss an item. An item has one choice: a new one replaces the old."""
    session.merge(ItemChoice(item_id=item_id, choice=choice, name=name, created_at=utcnow()))
    session.commit()


def clear_choice(session: Session, item_id: int) -> bool:
    """Forget the choice for an item; False when there was none."""
    row = session.get(ItemChoice, item_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
