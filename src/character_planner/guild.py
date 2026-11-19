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
from pydantic import BaseModel, computed_field
from sqlmodel import Session, col, select

from character_planner import fields, notify
from character_planner.builds import build_role
from character_planner.config import Settings
from character_planner.db import (
    Character,
    GuildAltGrouping,
    GuildMembership,
    NotificationDestination,
    NotificationOutbox,
    latest_by_kind,
)
from character_planner.links import item_url
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

    @computed_field
    @property
    def wowhead(self) -> str | None:
        return item_url(self.item_id)


class Member(BaseModel):
    character_id: int
    name: str
    character_class: str | None
    spec: str | None
    role: Role | None  # the member's own choice, else their spec's
    level: int | None
    yours: bool  # one of the signed-in user's characters
    # Characters with the same number are one player, who chose to show them so (#215,
    # ADR 0059): a number for this view only, never who they are. None: shown on its own.
    player: int | None = None


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
    roles: dict[str, dict[str, Role]],
    chosen: str | None,
    cls: str | None,
    spec: str | None,
    build: Role | None = None,
) -> Role | None:
    """The member's own choice in the view, then their build's role (#216), then their
    synced spec's (ADR 0042, ADR 0060)."""
    if chosen in ROLES:
        return chosen  # type: ignore[return-value]
    if build is not None:
        return build
    if cls and spec:
        return roles.get(cls, {}).get(spec)
    return None


def _number_players(
    session: Session,
    members: list[Member],
    owners: dict[int, int | None],
    region: str,
    guild_id: int,
) -> None:
    """Give the characters of each player who chose grouping here one number (#215)."""
    grouped = set(
        session.exec(
            select(GuildAltGrouping.user_id).where(
                col(GuildAltGrouping.region) == region,
                col(GuildAltGrouping.guild_id) == guild_id,
            )
        ).all()
    )
    numbers: dict[int, int] = {}
    for member in members:
        owner = owners.get(member.character_id)
        if owner is None or owner not in grouped:
            continue
        member.player = numbers.setdefault(owner, len(numbers) + 1)
    # A "player" of one character tells nothing: shown on its own.
    counts = {n: sum(m.player == n for m in members) for n in numbers.values()}
    for member in members:
        if member.player is not None and counts[member.player] < 2:
            member.player = None


def _default_going(members: list[Member], viewing: int) -> list[int]:
    """Everyone, but one character per grouped player: the one viewing if it's theirs,
    else their highest level."""
    best: dict[int, Member] = {}
    for member in members:
        if member.player is None:
            continue
        current = best.get(member.player)
        if current is None or (
            current.character_id != viewing
            and (member.character_id == viewing or (member.level or 0) > (current.level or 0))
        ):
            best[member.player] = member
    return [
        m.character_id
        for m in members
        if m.player is None or best[m.player].character_id == m.character_id
    ]


def _one_per_player(chosen: list[int], by_id: dict[int, Member]) -> list[int]:
    """A player runs a dungeon on one character at a time: the first chosen of each."""
    seen: set[int] = set()
    out: list[int] = []
    for character_id in chosen:
        player = by_id[character_id].player
        if player is not None:
            if player in seen:
                continue
            seen.add(player)
        out.append(character_id)
    return out


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
    owners: dict[int, int | None] = {}  # character -> its user, for grouping only
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
        owners[row.character_id] = character.user_id
        members.append(
            Member(
                character_id=row.character_id,
                name=f"{character.name} {character.surname}".strip(),
                character_class=cls,
                spec=spec.name if spec else None,
                role=_role_of(
                    roles,
                    row.role,
                    cls,
                    spec.name if spec else None,
                    build_role(session, settings.curated_dir, row.character_id),
                ),
                level=character_level(profile.payload if profile else None),
                yours=user_id is not None and character.user_id == user_id,
            )
        )
        recommendations[row.character_id] = jobs.recommendations_for(
            session, settings, row.character_id
        ).dungeons
    members.sort(key=lambda m: (not m.yours, m.name))
    _number_players(session, members, owners, mine.region, guild.id)

    ids = {m.character_id for m in members}
    by_id = {m.character_id: m for m in members}
    chosen = _one_per_player(
        [i for i in (going or _default_going(members, character_id)) if i in ids], by_id
    )
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


# --- your guilds: the picker, bulk joins and alt grouping (#215, ADR 0059) -----------------


class MyGuildCharacter(BaseModel):
    id: int
    name: str
    joined: bool  # in the guild's view now
    role: Role | None  # its own choice in the view, if any


class MyGuild(BaseModel):
    region: str
    guild_id: int
    name: str
    grouped: bool  # this player shows their characters here as one player
    characters: list[MyGuildCharacter]  # the user's characters in this guild


class MyGuilds(BaseModel):
    guilds: list[MyGuild]


class NotYours(Exception):
    """A character that isn't the user's, or isn't in the guild (404: nothing to tell)."""


def _grouped(session: Session, user_id: int, region: str, guild_id: int) -> GuildAltGrouping | None:
    return session.exec(
        select(GuildAltGrouping).where(
            col(GuildAltGrouping.user_id) == user_id,
            col(GuildAltGrouping.region) == region,
            col(GuildAltGrouping.guild_id) == guild_id,
        )
    ).first()


def my_guilds(session: Session, user_id: int) -> MyGuilds:
    """The guilds the user's characters are in, by their newest profiles, with which of
    them are in each guild's view."""
    guilds: dict[tuple[str, int], MyGuild] = {}
    characters = session.exec(
        select(Character).where(col(Character.user_id) == user_id).order_by(col(Character.id))
    ).all()
    for character in characters:
        assert character.id is not None
        guild = profile_guild(session, character.id)
        if guild is None:
            continue
        key = (character.region, guild.id)
        entry = guilds.get(key)
        if entry is None:
            entry = guilds[key] = MyGuild(
                region=character.region,
                guild_id=guild.id,
                name=guild.name,
                grouped=_grouped(session, user_id, character.region, guild.id) is not None,
                characters=[],
            )
        row = current_member(session, character.id)
        entry.characters.append(
            MyGuildCharacter(
                id=character.id,
                name=f"{character.name} {character.surname}".strip(),
                joined=row is not None,
                role=row.role if row is not None and row.role in ROLES else None,  # type: ignore[arg-type]
            )
        )
    return MyGuilds(guilds=sorted(guilds.values(), key=lambda g: g.name))


def _in_guild(
    session: Session, user_id: int, region: str, guild_id: int, ids: list[int]
) -> list[Character]:
    out: list[Character] = []
    for character_id in ids:
        character = session.get(Character, character_id)
        guild = profile_guild(session, character_id)
        if (
            character is None
            or character.user_id != user_id
            or character.region != region
            or guild is None
            or guild.id != guild_id
        ):
            raise NotYours(f"No character {character_id} of yours in that guild")
        out.append(character)
    return out


def join_many(
    session: Session,
    user_id: int,
    region: str,
    guild_id: int,
    *,
    join: list[int],
    leave: list[int],
    role: Role | None = None,
    shared_alerts: list[str] | None = None,
) -> None:
    """Join the guild's view with several of the user's characters, and leave with others:
    each still per character (ADR 0042). A role given applies to those joining; shared
    alerts given are set for each of them (#163). Raises NotYours before changing anything."""
    joining = _in_guild(session, user_id, region, guild_id, join)
    leaving = _in_guild(session, user_id, region, guild_id, leave)
    for character in joining:
        assert character.id is not None
        current = membership(session, character.id)
        keep = current.role if current is not None and role is None else role
        set_membership(session, character, True, keep)  # type: ignore[arg-type]
        if shared_alerts is not None:
            set_shared_alerts(session, character.id, shared_alerts)
    for character in leaving:
        set_membership(session, character, False, None)


def set_grouping(session: Session, user_id: int, region: str, guild_id: int, on: bool) -> None:
    """Show the user's characters in this guild's view as one player, or not."""
    row = _grouped(session, user_id, region, guild_id)
    if on and row is None:
        session.add(GuildAltGrouping(user_id=user_id, region=region, guild_id=guild_id))
    elif not on and row is not None:
        session.delete(row)
    session.commit()
