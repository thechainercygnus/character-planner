"""The guild view (#18, ADR 0042): plan dungeon runs with guildmates.

Only with users on, and only for opted-in members: a character opts into the guild its
profile names, and then sees every other opted-in member of that guild. Each member's
needs come from their own recommendations (their weights, rules and dismissals), so the
group ranking adds up what each would actually take from a dungeon.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.config import Settings
from character_planner.db import Character, GuildMembership, latest_by_kind
from character_planner.recommend import DungeonValue
from character_planner.views import character_level, parse_specialization

Role = Literal["tank", "healer", "dps"]
ROLES: tuple[Role, ...] = ("tank", "healer", "dps")


class GuildInfo(BaseModel):
    id: int
    name: str


class MemberNeed(BaseModel):
    item: str
    item_id: int
    slot: str
    score_gain: float


class Member(BaseModel):
    character_id: int
    name: str
    character_class: str | None
    spec: str | None
    role: Role | None  # the member's own choice, else their spec's
    level: int | None
    yours: bool  # one of the signed-in user's characters


class GroupDungeon(BaseModel):
    dungeon_id: str
    dungeon: str
    min_level: int | None
    max_level: int | None
    total_gain: float  # summed over the members going
    in_range: list[int]  # members going whose level suits it
    needs: dict[int, list[MemberNeed]]  # member -> their upgrades here, biggest first


class GuildView(BaseModel):
    guild: GuildInfo | None  # from the character's newest profile; None if guildless
    opted_in: bool
    role: Role | None = None  # this character's own choice, if any
    members: list[Member] = []  # opted-in members, shown only to one
    going: list[int] = []
    roles: dict[str, int] = {}  # among the members going
    missing_roles: list[Role] = []
    dungeons: list[GroupDungeon] = []  # best for the group first


def load_roles(path: Path) -> dict[str, dict[str, Role]]:
    """Class -> spec -> role, from data/curated/roles.yaml."""
    with path.open(encoding="utf-8") as handle:
        data = fields.as_mapping(yaml.safe_load(handle))
    roles: dict[str, dict[str, Role]] = {}
    for cls, specs in data.items():
        roles[str(cls)] = {
            str(spec): role for spec, role in fields.as_mapping(specs).items() if role in ROLES
        }
    return roles


def profile_guild(session: Session, character_id: int) -> GuildInfo | None:
    profile = latest_by_kind(session, character_id).get("profile")
    payload = profile.payload if profile else None
    guild_id = fields.as_int(fields.get(payload, "guild", "id"))
    name = fields.name(fields.get(payload, "guild", "name"))
    return GuildInfo(id=guild_id, name=name) if guild_id is not None and name else None


def membership(session: Session, character_id: int) -> GuildMembership | None:
    return session.exec(
        select(GuildMembership).where(col(GuildMembership.character_id) == character_id)
    ).first()


class NoGuild(Exception):
    """Opting in a character whose profile names no guild."""


def set_membership(
    session: Session, character: Character, opted_in: bool, role: Role | None
) -> None:
    """Opt the character in (into the guild its profile names now) or out."""
    assert character.id is not None
    current = membership(session, character.id)
    if not opted_in:
        if current is not None:
            session.delete(current)
            session.commit()
        return
    guild = profile_guild(session, character.id)
    if guild is None:
        raise NoGuild("This character isn't in a guild: sync it after joining one")
    row = current or GuildMembership(
        character_id=character.id, region=character.region, guild_id=guild.id, guild_name=""
    )
    row.guild_id, row.guild_name, row.region, row.role = (
        guild.id,
        guild.name,
        character.region,
        role,
    )
    session.add(row)
    session.commit()


def _role_of(
    roles: dict[str, dict[str, Role]], chosen: str | None, cls: str | None, spec: str | None
) -> Role | None:
    if chosen in ROLES:
        return chosen  # type: ignore[return-value]
    if cls and spec:
        return roles.get(cls, {}).get(spec)
    return None


def guild_view(
    session: Session,
    settings: Settings,
    character_id: int,
    user_id: int | None,
    going: list[int] | None = None,
) -> GuildView:
    """The character's guild view: the guild, and, once opted in, its opted-in members,
    their roles and the dungeons best for the members going (all of them by default)."""
    from character_planner import jobs

    guild = profile_guild(session, character_id)
    mine = membership(session, character_id)
    if guild is None or mine is None or mine.guild_id != guild.id:
        return GuildView(guild=guild, opted_in=False)

    roles = load_roles(settings.curated_dir / "roles.yaml")
    rows = session.exec(
        select(GuildMembership).where(
            col(GuildMembership.guild_id) == guild.id,
            col(GuildMembership.region) == mine.region,
        )
    ).all()
    members: list[Member] = []
    recommendations: dict[int, list[DungeonValue]] = {}
    for row in rows:
        # Still in the guild by its newest profile: a member who left drops out.
        here = profile_guild(session, row.character_id)
        character = session.get(Character, row.character_id)
        if here is None or here.id != guild.id or character is None:
            continue
        latest = latest_by_kind(session, row.character_id)
        profile = latest.get("profile")
        specs = latest.get("specializations")
        cls = fields.name(
            fields.get(profile.payload if profile else None, "character_class", "name")
        )
        spec = parse_specialization(specs.payload if specs else None)
        members.append(
            Member(
                character_id=row.character_id,
                name=f"{character.name} {character.surname}".strip(),
                character_class=cls,
                spec=spec.name if spec else None,
                role=_role_of(roles, row.role, cls, spec.name if spec else None),
                level=character_level(profile.payload if profile else None),
                yours=user_id is not None and character.user_id == user_id,
            )
        )
        recommendations[row.character_id] = jobs.recommendations_for(
            session, settings, row.character_id
        ).dungeons
    members.sort(key=lambda m: (not m.yours, m.name))

    ids = {m.character_id for m in members}
    chosen = [i for i in (going or sorted(ids)) if i in ids]
    by_id = {m.character_id: m for m in members}
    counts = {role: sum(1 for i in chosen if by_id[i].role == role) for role in ROLES}
    missing: list[Role] = [r for r in ("tank", "healer") if counts[r] == 0] if chosen else []

    dungeons: dict[str, GroupDungeon] = {}
    for member_id in chosen:
        level = by_id[member_id].level
        for value in recommendations[member_id]:
            group = dungeons.setdefault(
                value.dungeon_id,
                GroupDungeon(
                    dungeon_id=value.dungeon_id,
                    dungeon=value.dungeon,
                    min_level=value.min_level,
                    max_level=value.max_level,
                    total_gain=0,
                    in_range=[],
                    needs={},
                ),
            )
            group.total_gain = round(group.total_gain + value.total_gain, 2)
            group.needs[member_id] = [
                MemberNeed(
                    item=u.item.name,
                    item_id=u.item.item_id,
                    slot=u.slot,
                    score_gain=u.score_gain,
                )
                for u in value.upgrades
            ]
            low, high = value.min_level or 0, value.max_level or 999
            if level is not None and low <= level <= high:
                group.in_range.append(member_id)
    ranked = sorted(dungeons.values(), key=lambda d: (-d.total_gain, d.dungeon))
    return GuildView(
        guild=guild,
        opted_in=True,
        role=mine.role if mine.role in ROLES else None,  # type: ignore[arg-type]
        members=members,
        going=chosen,
        roles=dict(counts),
        missing_roles=missing,
        dungeons=ranked,
    )
