"""The account page (#217, ADR 0058): one user's characters, guilds and data in one place.

It reads what's already stored, per character: its level and class, its last sync, its
guild and whether it's in the guild view (ADR 0042), and its newest game-data import
(#184). Without users (a single-person instance) it's every character, and no account.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.characters import character_list
from character_planner.db import GameDataImport, GuildMembership, User, latest_by_kind


class MyCharacter(BaseModel):
    id: int
    name: str  # name and surname
    region: str
    character_class: str | None
    level: int | None
    default: bool  # the one a request without X-Character-Id gets (ADR 0036)
    last_sync: datetime | None  # its newest profile from Battle.net
    guild: str | None  # as its newest profile names it
    in_guild_view: bool  # joined its guild's view (ADR 0042)
    game_data_at: datetime | None  # when the game wrote its newest addon import


class AccountView(BaseModel):
    users: bool
    # The signed-in Battle.net account; None without users.
    account_id: int | None = None
    role: str | None = None
    characters: list[MyCharacter]


def account_view(session: Session, user_id: int | None, users: bool) -> AccountView:
    listed = character_list(session, user_id if users else None)
    ids = [c.id for c in listed.characters]
    joined = set(
        session.exec(
            select(GuildMembership.character_id).where(col(GuildMembership.character_id).in_(ids))
        ).all()
    )
    imports = {
        row.character_id: row.captured_at
        for row in session.exec(
            select(GameDataImport).where(col(GameDataImport.character_id).in_(ids))
        ).all()
    }
    rows: list[MyCharacter] = []
    for c in listed.characters:
        profile = latest_by_kind(session, c.id).get("profile")
        payload = profile.payload if profile else None
        rows.append(
            MyCharacter(
                id=c.id,
                name=" ".join(part for part in (c.name, c.surname) if part),
                region=c.region,
                character_class=c.character_class,
                level=c.level,
                default=c.id == listed.default_id,
                last_sync=profile.captured_at if profile else None,
                guild=fields.name(fields.get(payload, "guild", "name")),
                in_guild_view=c.id in joined,
                game_data_at=imports.get(c.id),
            )
        )
    user = session.get(User, user_id) if users and user_id is not None else None
    return AccountView(
        users=users,
        account_id=user.account_id if user else None,
        role=user.role if user else None,
        characters=rows,
    )
