"""A character's public page (#42, ADR 0063): opt-in, read-only, at an unguessable link.

The owner turns it on per character; that makes a random token, and the link carries it
in its #public= fragment, so it never reaches the server's logs. The web app posts the
token to read the page. Turning the page off deletes the token; a new link replaces it.

What it shows is `PublicCharacter`: the last sync's header, equipment, stats, professions
and spent talents. It's built from stored snapshots only, so viewing it never calls
Blizzard or Forever Companion, and it follows their 30-day rule: when the snapshots go,
the page has nothing to show. Plans, targets, weights, game data from the addon, the
account and other characters are never in it.
"""

import re
import secrets
from datetime import datetime
from typing import Final

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import NoCharacter, PublicPage, owned, utcnow
from character_planner.views import (
    CharacterView,
    EquippedItem,
    Profession,
    Specialization,
    Stats,
)

TOKEN_BYTES: Final = 24  # 192 bits, 32 characters of URL-safe base64
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32}")


class PublicCharacter(BaseModel):
    """Everything a public page shows, and nothing else: each field is named here, so a
    field added to CharacterView doesn't become public by accident."""

    name: str | None = None
    surname: str | None = None
    level: int | None = None
    race: str | None = None
    character_class: str | None = None
    guild: str | None = None
    equipped_item_level: float | None = None
    gear_slots_filled: int = 0
    captured_at: datetime | None = None
    stats: Stats | None = None
    professions: list[Profession] = []
    specialization: Specialization | None = None
    equipment: list[EquippedItem] = []


class PublicPageState(BaseModel):
    """For the owner: whether the page is on, and its token to build the link."""

    enabled: bool
    token: str | None = None
    created_at: datetime | None = None


def public_view(view: CharacterView) -> PublicCharacter:
    return PublicCharacter.model_validate(
        view.model_dump(include=set(PublicCharacter.model_fields))
    )


def state(session: Session, character_id: int | None) -> PublicPageState:
    page = owned(session, PublicPage, character_id)
    if page is None:
        return PublicPageState(enabled=False)
    return PublicPageState(enabled=True, token=page.token, created_at=page.created_at)


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def enable(session: Session, character_id: int | None) -> PublicPageState:
    """Turn the page on; already on, the link stays as it is."""
    if character_id is None:
        raise NoCharacter("No character yet: add one in the app")
    if owned(session, PublicPage, character_id) is None:
        session.add(PublicPage(character_id=character_id, token=_new_token()))
        session.commit()
    return state(session, character_id)


def disable(session: Session, character_id: int | None) -> PublicPageState:
    """Turn the page off: the token is deleted, so the old link stops working."""
    page = owned(session, PublicPage, character_id)
    if page is not None:
        session.delete(page)
        session.commit()
    return PublicPageState(enabled=False)


def regenerate(session: Session, character_id: int | None) -> PublicPageState | None:
    """A new link in place of the old one; None when the page is off."""
    page = owned(session, PublicPage, character_id)
    if page is None:
        return None
    page.token = _new_token()
    page.created_at = utcnow()
    session.add(page)
    session.commit()
    return state(session, character_id)


def character_for(session: Session, token: str) -> int | None:
    """The character a token shows, or None for a malformed, old or unknown one."""
    if not _TOKEN.fullmatch(token):
        return None
    page = session.exec(select(PublicPage).where(col(PublicPage.token) == token)).first()
    return page.character_id if page else None
