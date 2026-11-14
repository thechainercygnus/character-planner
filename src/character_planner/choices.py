"""Items dismissed from the Upgrades tab (ADR 0012).

Dismissed items are stored in the database and never suggested; they replaced
recommend.yaml's exclude_item_ids (ADR 0016). Pinned targets used to live here too; they're gear
targets now (ADR 0014), and migrate_target_choices moves old ones across.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import ItemChoice, delete_owned, save_owned, utcnow

ChoiceKind = Literal["dismissed"]


class ItemChoiceView(BaseModel):
    item_id: int
    name: str
    choice: ChoiceKind
    created_at: datetime


class Choices(BaseModel):
    """Dismissed item ids, as the recommendation engine takes them."""

    dismissed: set[int] = set()


def list_choices(session: Session, character_id: int | None) -> list[ItemChoiceView]:
    """The character's dismissed items, newest first."""
    rows = session.exec(
        select(ItemChoice)
        .where(col(ItemChoice.character_id) == character_id)
        .order_by(col(ItemChoice.created_at).desc(), col(ItemChoice.item_id))
    ).all()
    return [
        ItemChoiceView.model_validate(r, from_attributes=True)
        for r in rows
        if r.choice == "dismissed"
    ]


def stored_choices(session: Session, character_id: int | None) -> Choices:
    return Choices(dismissed={row.item_id for row in list_choices(session, character_id)})


def set_choice(
    session: Session, item_id: int, name: str, choice: ChoiceKind, character_id: int | None
) -> None:
    """Dismiss an item for the character."""
    values = {"choice": choice, "name": name, "created_at": utcnow()}
    save_owned(session, ItemChoice, character_id, {"item_id": item_id}, values)
    session.commit()


def take_target_choices(session: Session, character_id: int | None) -> list[int]:
    """Remove the character's pins stored before ADR 0014 and return their item ids,
    oldest first."""
    rows = session.exec(
        select(ItemChoice)
        .where(col(ItemChoice.character_id) == character_id, col(ItemChoice.choice) == "target")
        .order_by(col(ItemChoice.created_at))
    ).all()
    ids = [row.item_id for row in rows]
    for row in rows:
        session.delete(row)
    session.commit()
    return ids


def clear_choice(session: Session, item_id: int, character_id: int | None) -> bool:
    """Forget the character's choice for an item; False when there was none."""
    if not delete_owned(session, ItemChoice, character_id, item_id=item_id):
        return False
    session.commit()
    return True
