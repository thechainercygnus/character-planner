"""Roles and permissions, when users are on (#237, ADR 0055).

Every user has a role: the admin (the first sign-in, ADR 0037), a superuser, or a user.
What a role may do is a list of named permissions kept in the `role` table, so changing
what superusers may do is a data change, not a rewrite. Routes check a permission by name
(app.py's ROUTE_PERMISSIONS), never a role.

- **The admin has every permission,** whatever its row says, so a permission added later
  never locks the admin out.
- **One admin.** The admin makes users superusers and back; nobody grants or takes the
  admin's role.
- **Superusers are instance-wide** (Bryce, 2026-11-19): their permissions apply across the
  instance. Scoping them to particular guilds can come later, as data.
"""

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner.db import Character, Role, User

ADMIN: Final = "admin"
SUPERUSER: Final = "superuser"
USER: Final = "user"
RoleName = Literal["admin", "superuser", "user"]
GRANTABLE: Final = (SUPERUSER, USER)

# Every permission, with what it allows: the admin area shows these. A route's permission
# is in app.py's ROUTE_PERMISSIONS.
PERMISSIONS: Final[dict[str, str]] = {
    "accounts.view": "See every account, its role and its characters",
    "roles.manage": "Make a user a superuser, or a user again",
    "data.refresh": "Refresh the shared game data: items, the item pool, enchants and talents",
    "enchants.correct": "Correct the shared enchant data: material levels and crafted effects",
    "discord.signup": "Update the Discord bot's pinned sign-up message",
    "users.delete": "Delete an account and everything stored for it",
    "users.export": "Download everything stored for an account, for an access request",
    "log.view": "See the log of what the admin area did",
    "backups.manage": "See the backups, and back up now",
    "signups.manage": "Open or close sign-ups, and invite someone while they're closed",
}
# What each role starts with: migrations 0019 to 0024 store these.
DEFAULTS: Final[dict[str, list[str]]] = {
    ADMIN: sorted(PERMISSIONS),
    SUPERUSER: ["accounts.view", "data.refresh", "enchants.correct"],
    USER: [],
}


class RoleError(ValueError):
    """A role change that isn't allowed: the message says why."""


def permissions_of(session: Session, role: str) -> frozenset[str]:
    """What a role may do. The admin may do everything (ADR 0055)."""
    if role == ADMIN:
        return frozenset(PERMISSIONS)
    row = session.get(Role, role)
    return frozenset(p for p in (row.permissions if row else []) if p in PERMISSIONS)


class RoleView(BaseModel):
    name: str
    permissions: list[str]


class AdminCharacter(BaseModel):
    id: int
    name: str
    region: str
    character_class: str | None


class Account(BaseModel):
    """What the planner stores about an account, and no more (#237): it's for running the
    instance, not watching people."""

    user_id: int
    account_id: int  # the Battle.net account id
    role: str
    created_at: datetime
    last_sign_in_at: datetime
    characters: list[AdminCharacter]


class AdminView(BaseModel):
    accounts: list[Account]
    roles: list[RoleView]
    permissions: dict[str, str]  # name -> what it allows


def _account(user: User, characters: list[Character]) -> Account:
    assert user.id is not None
    return Account(
        user_id=user.id,
        account_id=user.account_id,
        role=user.role,
        created_at=user.created_at,
        last_sign_in_at=user.last_sign_in_at,
        characters=[
            AdminCharacter(
                id=c.id,
                name=" ".join(part for part in (c.name, c.surname) if part),
                region=c.region,
                character_class=c.character_class,
            )
            for c in characters
            if c.id is not None
        ],
    )


def admin_view(session: Session) -> AdminView:
    """Every account, oldest first, with its characters; and what each role may do."""
    users = session.exec(select(User).order_by(col(User.id))).all()
    owned: dict[int, list[Character]] = {}
    for character in session.exec(select(Character).order_by(col(Character.id))).all():
        if character.user_id is not None:
            owned.setdefault(character.user_id, []).append(character)
    order = {ADMIN: 0, SUPERUSER: 1, USER: 2}
    roles = sorted(session.exec(select(Role)).all(), key=lambda r: order.get(r.name, 3))
    return AdminView(
        accounts=[_account(u, owned.get(u.id or 0, [])) for u in users],
        roles=[
            RoleView(name=r.name, permissions=sorted(permissions_of(session, r.name)))
            for r in roles
        ],
        permissions=dict(PERMISSIONS),
    )


def set_role(session: Session, user_id: int, role: str) -> Account:
    """Make a user a superuser, or a user again. Raises LookupError for no such user, and
    RoleError for the admin's role or a role that can't be granted."""
    if role not in GRANTABLE:
        raise RoleError(f"Only {' or '.join(GRANTABLE)} can be granted")
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"No user {user_id}")
    if user.role == ADMIN:
        raise RoleError("The admin's role can't be changed")
    user.role = role
    session.add(user)
    session.commit()
    session.refresh(user)
    characters = session.exec(
        select(Character).where(col(Character.user_id) == user_id).order_by(col(Character.id))
    ).all()
    return _account(user, list(characters))
