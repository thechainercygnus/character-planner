"""The guild view (#18, ADR 0042): plan dungeon runs with guildmates.

Only with users on, and only for opted-in members: a character opts into the guild its
profile names, and then sees every other opted-in member of that guild. Each member's
needs come from their own recommendations (their weights, rules and dismissals), so the
group ranking adds up what each would actually take from a dungeon.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields, notify
from character_planner.config import Settings
from character_planner.db import (
    Character,
    GuildMembership,
    NotificationDestination,
    NotificationOutbox,
    latest_by_kind,
)
from character_planner.recommend import DungeonValue
from character_planner.views import character_level, parse_specialization

Role = Literal["tank", "healer", "dps"]
ROLES: tuple[Role, ...] = ("tank", "healer", "dps")

logger = logging.getLogger(__name__)


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


class GuildChannel(BaseModel):
    """The guild's alert channel (#163), as members see it: the webhook masked."""

    url: str
    set_by: str | None  # the member who set it; None once they've left the view
    set_at: datetime
    last_sent_at: datetime | None
    last_error: str | None


class GuildView(BaseModel):
    guild: GuildInfo | None  # from the character's newest profile; None if guildless
    opted_in: bool
    role: Role | None = None  # this character's own choice, if any
    members: list[Member] = []  # opted-in members, shown only to one
    going: list[int] = []
    roles: dict[str, int] = {}  # among the members going
    missing_roles: list[Role] = []
    dungeons: list[GroupDungeon] = []  # best for the group first
    # The guild's alert channel (#163), and which of this character's alerts post there.
    channel: GuildChannel | None = None
    shared_alerts: list[str] = []
    alerts: list[notify.AlertInfo] = []  # the alerts a member can share: character ones


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


class NotAMember(Exception):
    """Changing the guild's channel from a character that isn't in its view (403)."""


# --- the guild's alert channel (#163, ADR 0046) ---------------------------------------------

GUILD = notify.GUILD


def guild_key(region: str, guild_id: int) -> str:
    return f"{region}:{guild_id}"


def channel_of(session: Session, region: str, guild_id: int) -> NotificationDestination | None:
    return session.exec(
        select(NotificationDestination).where(
            NotificationDestination.kind == GUILD,
            NotificationDestination.guild_key == guild_key(region, guild_id),
        )
    ).first()


def _drop_channel(session: Session, channel: NotificationDestination) -> None:
    for item in session.exec(
        select(NotificationOutbox).where(NotificationOutbox.destination_id == channel.id)
    ).all():
        session.delete(item)
    session.flush()
    session.delete(channel)


def current_member(session: Session, character_id: int) -> GuildMembership | None:
    """The character's membership, if it's still in that guild by its newest profile."""
    row = membership(session, character_id)
    guild = profile_guild(session, character_id)
    return row if row is not None and guild is not None and guild.id == row.guild_id else None


def set_channel(session: Session, character_id: int, url: str) -> None:
    """Set or replace the guild's channel: any member in the view may (Bryce, ADR 0046)."""
    row = current_member(session, character_id)
    if row is None:
        raise NotAMember("Join the guild view first")
    url = notify.valid_webhook(url)
    existing = channel_of(session, row.region, row.guild_id)
    if existing is not None:
        _drop_channel(session, existing)
    session.add(
        NotificationDestination(
            name=row.guild_name[:60] or "Guild",
            kind=GUILD,
            audience="user",
            url=url,
            alerts=list(notify.USER_ALERTS),
            guild_key=guild_key(row.region, row.guild_id),
            set_by_character_id=character_id,
        )
    )
    session.commit()
    logger.info("Guild channel set for guild %s", row.guild_id)


def remove_channel(session: Session, character_id: int) -> None:
    row = current_member(session, character_id)
    if row is None:
        raise NotAMember("Join the guild view first")
    existing = channel_of(session, row.region, row.guild_id)
    if existing is not None:
        _drop_channel(session, existing)
        session.commit()
        logger.info("Guild channel removed for guild %s", row.guild_id)


def set_shared_alerts(session: Session, character_id: int, alerts: list[str]) -> None:
    """Which of the character's alerts post to the guild's channel."""
    row = current_member(session, character_id)
    if row is None:
        raise NotAMember("Join the guild view first")
    wanted = notify.clean_alerts(alerts, "user", admin=False)
    row.shared_alerts = wanted
    session.add(row)
    session.commit()


def drop_empty_channels(session: Session) -> int:
    """Remove channels whose guild has no member left in the view: nobody can see or
    change them any more. Doesn't commit."""
    keys = {
        guild_key(row.region, row.guild_id) for row in session.exec(select(GuildMembership)).all()
    }
    dropped = 0
    for channel in session.exec(
        select(NotificationDestination).where(NotificationDestination.kind == GUILD)
    ).all():
        if channel.guild_key not in keys:
            _drop_channel(session, channel)
            dropped += 1
    return dropped


def channel_view(session: Session, row: GuildMembership) -> GuildChannel | None:
    channel = channel_of(session, row.region, row.guild_id)
    if channel is None:
        return None
    setter = (
        session.get(Character, channel.set_by_character_id)
        if channel.set_by_character_id is not None
        else None
    )
    still_member = setter is not None and setter.id is not None and membership(session, setter.id)
    return GuildChannel(
        url=notify.masked(channel.url),
        set_by=f"{setter.name} {setter.surname}".strip() if setter and still_member else None,
        set_at=channel.created_at,
        last_sent_at=channel.last_sent_at,
        last_error=channel.last_error,
    )


def set_membership(
    session: Session, character: Character, opted_in: bool, role: Role | None
) -> None:
    """Opt the character in (into the guild its profile names now) or out."""
    assert character.id is not None
    current = membership(session, character.id)
    if not opted_in:
        if current is not None:
            session.delete(current)
            session.flush()
            drop_empty_channels(session)  # the last member out takes the channel (#163)
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
        channel=channel_view(session, mine),
        shared_alerts=list(mine.shared_alerts or []),
        alerts=[a for a in notify.ALERTS if a.audience == "user"],
    )
