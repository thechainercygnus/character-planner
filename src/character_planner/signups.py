"""Sign-ups and invites, when users are on (#239, ADR 0057).

- **Sign-ups:** open or closed. `PLANNER_SIGNUPS` is the default; once the admin opens or
  closes them in the app, that choice wins for good (Bryce, 2026-11-18).
- **Invites:** a link that lets one person sign up while sign-ups are closed. One use,
  valid for 7 days, revocable (Bryce, 2026-11-19). The link carries a random token in its
  fragment (`#invite=`), which never reaches the server's logs; only the token's SHA-256
  is stored. An existing account signing in never spends an invite.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Final, Literal

from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, col, select

from character_planner.companion import as_utc
from character_planner.config import Settings
from character_planner.db import InstanceSetting, Invite, utcnow

SIGNUPS: Final = "signups_open"
VALID_FOR: Final = timedelta(days=7)
# Spent, revoked or expired invites are kept this long, to show who used them, then pruned.
KEEP_CLOSED: Final = timedelta(days=30)
InviteState = Literal["open", "used", "revoked", "expired"]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SignupsView(BaseModel):
    open: bool
    # Where it comes from: the app's choice, or PLANNER_SIGNUPS (the default).
    source: Literal["app", "setting"]
    changed_at: datetime | None = None


def signups(session: Session, settings: Settings) -> SignupsView:
    row = session.get(InstanceSetting, SIGNUPS)
    if row is None:
        return SignupsView(open=settings.planner_signups, source="setting")
    return SignupsView(open=bool(row.value), source="app", changed_at=row.updated_at)


def signups_open(session: Session, settings: Settings) -> bool:
    return signups(session, settings).open


def set_signups(session: Session, settings: Settings, open_: bool) -> SignupsView:
    row = session.get(InstanceSetting, SIGNUPS) or InstanceSetting(key=SIGNUPS, value=open_)
    row.value = open_
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return signups(session, settings)


class InviteView(BaseModel):
    id: int
    created_at: datetime
    expires_at: datetime
    created_by_account_id: int | None
    used_at: datetime | None
    used_by_account_id: int | None
    revoked_at: datetime | None
    state: InviteState


class NewInvite(BaseModel):
    invite: InviteView
    # Shown once: the link is the web app's address with #invite=<token>.
    token: str


def state_of(invite: Invite, now: datetime | None = None) -> InviteState:
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    if as_utc(invite.expires_at) <= (now or utcnow()):
        return "expired"
    return "open"


def _view(invite: Invite) -> InviteView:
    assert invite.id is not None
    return InviteView(
        id=invite.id,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        created_by_account_id=invite.created_by_account_id,
        used_at=invite.used_at,
        used_by_account_id=invite.used_by_account_id,
        revoked_at=invite.revoked_at,
        state=state_of(invite),
    )


def create_invite(session: Session, actor: int | None) -> NewInvite:
    token = secrets.token_urlsafe(32)
    invite = Invite(
        token_hash=_hash(token), expires_at=utcnow() + VALID_FOR, created_by_account_id=actor
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return NewInvite(invite=_view(invite), token=token)


def invites(session: Session) -> list[InviteView]:
    """Every invite still kept, newest first."""
    rows = session.exec(select(Invite).order_by(col(Invite.id).desc())).all()
    return [_view(row) for row in rows]


def revoke(session: Session, invite_id: int) -> InviteView:
    """Raises LookupError for no such invite, ValueError for one that isn't open."""
    invite = session.get(Invite, invite_id)
    if invite is None:
        raise LookupError(f"No invite {invite_id}")
    if state_of(invite) != "open":
        raise ValueError(f"That invite is {state_of(invite)} already")
    invite.revoked_at = utcnow()
    session.add(invite)
    session.commit()
    return _view(invite)


def open_invite(session: Session, token: str | None) -> Invite | None:
    """The invite a token is for, while it can still be used."""
    if not token:
        return None
    invite = session.exec(select(Invite).where(col(Invite.token_hash) == _hash(token))).first()
    return invite if invite is not None and state_of(invite) == "open" else None


def spend(session: Session, invite: Invite, account_id: int) -> None:
    """Mark an invite used by a new account. Doesn't commit: the sign-in does."""
    invite.used_at = utcnow()
    invite.used_by_account_id = account_id
    session.add(invite)


def prune(session: Session, now: datetime | None = None) -> int:
    """Delete invites closed (used, revoked or expired) more than KEEP_CLOSED ago."""
    cutoff = (now or utcnow()) - KEEP_CLOSED
    statements = (
        delete(Invite).where(col(Invite.used_at) < cutoff),
        delete(Invite).where(col(Invite.revoked_at) < cutoff),
        delete(Invite).where(col(Invite.used_at).is_(None), col(Invite.expires_at) < cutoff),
    )
    count = 0
    for statement in statements:
        result = session.exec(statement)  # pyright: ignore[reportCallIssue, reportArgumentType]
        count += int(getattr(result, "rowcount", 0) or 0)
    session.commit()
    return count
