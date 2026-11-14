"""Users and sessions, when the operator turns users on (#16, ADR 0037).

A user is a Battle.net account, keyed by the id /profile/user/wow returns. Signing in
makes a session: a random token in an HttpOnly cookie, stored here only as its SHA-256.
The first account to sign in becomes the admin and adopts every character without an
owner; later accounts need sign-ups open. Nothing here logs a token.
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select

from character_planner.blizzard import oauth
from character_planner.companion import as_utc
from character_planner.db import Character, User, UserSession, UserToken, utcnow

logger = logging.getLogger(__name__)

COOKIE = "planner_session"
SESSION_LENGTH = timedelta(days=30)


class SignupsClosed(Exception):
    """A new account signing in while sign-ups are closed."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    """A new session for the user; returns the token for the cookie (never stored)."""
    assert user.id is not None
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(token_hash=_hash(token), user_id=user.id, expires_at=utcnow() + SESSION_LENGTH)
    )
    session.commit()
    return token


def user_for(session: Session, token: str | None) -> User | None:
    """The user a session cookie belongs to; None when it's missing, unknown or expired."""
    if not token:
        return None
    row = session.exec(
        select(UserSession).where(col(UserSession.token_hash) == _hash(token))
    ).first()
    if row is None:
        return None
    if as_utc(row.expires_at) <= utcnow():
        session.delete(row)
        session.commit()
        return None
    return session.get(User, row.user_id)


def end_session(session: Session, token: str | None) -> None:
    """Sign out: the session stops working at once."""
    if not token:
        return
    row = session.exec(
        select(UserSession).where(col(UserSession.token_hash) == _hash(token))
    ).first()
    if row is not None:
        session.delete(row)
        session.commit()


def sign_in(session: Session, account_id: int, token: oauth.Token, *, signups_open: bool) -> User:
    """Find or create the user for a Battle.net account and keep its sign-in token.

    The very first account becomes the admin and adopts every character without an
    owner, so an instance turning users on keeps its data. Other new accounts need
    sign-ups open, else SignupsClosed."""
    user = session.exec(select(User).where(col(User.account_id) == account_id)).first()
    if user is None:
        first = session.exec(select(User)).first() is None
        if not first and not signups_open:
            raise SignupsClosed("Sign-ups are closed on this instance")
        user = User(account_id=account_id, is_admin=first)
        session.add(user)
        session.flush()
        if first:
            statement = (
                update(Character).where(col(Character.user_id).is_(None)).values(user_id=user.id)
            )
            result: Any = session.exec(statement)  # pyright: ignore[reportCallIssue, reportArgumentType]
            logger.info("First sign-in: admin created, %d characters adopted", result.rowcount or 0)
        else:
            logger.info("New user signed up")
    user.last_sign_in_at = utcnow()
    session.add(user)
    assert user.id is not None
    session.merge(
        UserToken(
            user_id=user.id,
            access_token=token.access_token,
            expires_at=token.expires_at,
            scope=token.scope,
        )
    )
    session.commit()
    session.refresh(user)
    return user


def user_token(session: Session, user_id: int) -> oauth.Token | None:
    """The user's Battle.net sign-in token while it's valid."""
    stored = session.get(UserToken, user_id)
    if stored is None:
        return None
    token = oauth.Token(stored.access_token, stored.expires_at, stored.scope)
    return None if token.expired else token


class LastAdmin(Exception):
    """The admin deleting their account while others still use the instance."""


def delete_user(session: Session, user_id: int) -> dict[str, int]:
    """Delete a user and everything stored for them (#16, ADR 0037): their characters with
    each one's data and settings, their sessions and their Battle.net token. The admin
    can't go while other users remain, or no one could run the instance."""
    from character_planner.characters import delete_character

    user = session.get(User, user_id)
    if user is None:
        return {}
    others = session.exec(select(User).where(col(User.id) != user_id)).first()
    if user.is_admin and others is not None:
        raise LastAdmin("Hand the instance over first: other users still need an admin")
    removed: dict[str, int] = {}
    owned = session.exec(select(Character).where(col(Character.user_id) == user_id)).all()
    for character in owned:
        assert character.id is not None
        for table, count in delete_character(session, character.id).items():
            removed[table] = removed.get(table, 0) + count
    sessions = session.exec(select(UserSession).where(col(UserSession.user_id) == user_id)).all()
    for row in sessions:
        session.delete(row)
    if sessions:
        removed["usersession"] = len(sessions)
    token = session.get(UserToken, user_id)
    if token is not None:
        session.delete(token)
        removed["usertoken"] = 1
    session.delete(user)
    removed["user"] = 1
    session.commit()
    logger.info("Deleted a user and %d rows", sum(removed.values()))
    return removed


def user_by_account(session: Session, account_id: int) -> User | None:
    return session.exec(select(User).where(col(User.account_id) == account_id)).first()
