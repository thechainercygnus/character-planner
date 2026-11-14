"""Tracked characters (#14, ADR 0036).

`.env` names the first character once: when the table is empty, `current_character`
creates it from CHARACTER_NAME, CHARACTER_SURNAME and BNET_REGION, and gives it every row
stored before characters existed. After that, the table decides, and those settings
aren't read again.
"""

import logging
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.config import Settings
from character_planner.db import (
    ActiveWeightPreset,
    Character,
    ClassQuestDone,
    ItemChoice,
    NotificationState,
    ProgressHistory,
    Snapshot,
    StoredGearTargets,
    StoredTalentPlan,
    StoredUsageRules,
    WeightPreset,
)

# Everything a character owns (ADR 0036): rows from before #14 are adopted by the first.
OWNED = (
    Snapshot,
    ProgressHistory,
    StoredTalentPlan,
    StoredUsageRules,
    StoredGearTargets,
    WeightPreset,
    ActiveWeightPreset,
    ItemChoice,
    ClassQuestDone,
    NotificationState,
)

logger = logging.getLogger(__name__)


def adopt_at_start(session: Session, settings: Settings) -> Character | None:
    """On start: the current character, seeded if needed, given any rows without an
    owner (a database downgraded past 0010 and upgraded again keeps its characters but
    copies settings back without one)."""
    character = current_character(session, settings)
    if character is not None and adopt_orphans(session, character):
        session.commit()
        logger.info("Gave rows without a character to %s", character.slug)
    return character


def first_character(session: Session) -> Character | None:
    return session.exec(select(Character).order_by(col(Character.id))).first()


def current_character(session: Session, settings: Settings) -> Character | None:
    """The character the app shows and syncs: the first one until the app can switch
    (#14's last step). Seeds it from settings on a database that has none."""
    return first_character(session) or seed_from_settings(session, settings)


def seed_from_settings(session: Session, settings: Settings) -> Character | None:
    if not settings.character_name:
        return None
    character = Character(
        region=settings.bnet_region,
        slug=settings.character_slug,
        name=settings.character_name,
        surname=settings.character_surname,
    )
    session.add(character)
    session.flush()
    adopted = adopt_orphans(session, character)
    refresh_from_profile(session, character)
    session.commit()
    session.refresh(character)
    logger.info(
        "Tracking %s (%s) from CHARACTER_NAME; %d stored rows adopted",
        character.slug,
        character.region,
        adopted,
    )
    return character


def adopt_orphans(session: Session, character: Character) -> int:
    """Give rows stored before #14 (no character) to this character."""
    adopted = 0
    for table in OWNED:
        statement = (
            update(table).where(col(table.character_id).is_(None)).values(character_id=character.id)
        )
        result: Any = session.exec(statement)  # pyright: ignore[reportCallIssue, reportArgumentType]
        adopted += int(result.rowcount or 0)
    return adopted


def refresh_from_profile(session: Session, character: Character) -> None:
    """Copy the id, class, race and faction from the character's newest profile."""
    profile = session.exec(
        select(Snapshot)
        .where(
            col(Snapshot.character_id) == character.id,
            col(Snapshot.kind) == "profile",
            col(Snapshot.status) == 200,
        )
        .order_by(col(Snapshot.captured_at).desc(), col(Snapshot.id).desc())
    ).first()
    payload = profile.payload if profile else None
    if payload is None:
        return
    blizzard_id = fields.as_int(fields.get(payload, "id"))
    character.blizzard_id = blizzard_id if blizzard_id is not None else character.blizzard_id
    character.character_class = (
        fields.name(fields.get(payload, "character_class", "name")) or character.character_class
    )
    character.race = fields.name(fields.get(payload, "race", "name")) or character.race
    faction = fields.get(payload, "faction", "type")
    character.faction = faction if isinstance(faction, str) else character.faction
    session.add(character)
