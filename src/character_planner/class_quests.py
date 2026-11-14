"""The class quest checklist (#8, ADR 0030): quests that unlock class abilities, by level.

Forever Companion's GET /class-quests lists every class's quests. Its CDN cache ignores
query strings (ADR 0004, 0029: `?class=warrior` returns all 44 quests), so it's fetched
unfiltered, and each quest is merged in by id as rares are: a filtered list served from
the cache can't remove any.

The list is filtered here by the character's class, faction and race. Done marks are set
by hand in the app, until there's an API source for completed quests.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.companion import BASE_URL
from character_planner.db import ClassQuestDone, CompanionClassQuest, latest_by_kind, utcnow
from character_planner.views import character_faction, character_view

logger = logging.getLogger(__name__)

# How far ahead "coming soon" looks, in levels.
SOON_LEVELS = 5

Status = Literal["done", "missed", "now", "soon", "later"]


class ClassQuest(BaseModel):
    id: str
    class_key: str  # "warrior": Forever Companion's class names, as key() makes them
    level: int
    name: str
    faction: str = "both"  # alliance, horde or both
    races: list[str] | None = None  # only these races ("night-elf"); None for any
    giver: str | None = None
    location: str | None = None
    reward: str | None = None
    essential: bool = False  # unlocks a core ability


class ClassQuestRow(ClassQuest):
    done: bool = False
    # missed: essential, at or below the character's level and not done (#8).
    status: Status


class ClassQuestChecklist(BaseModel):
    class_name: str | None  # as Blizzard names it ("Warrior")
    level: int | None
    soon_levels: int = SOON_LEVELS
    listed: int  # class quests stored, any class: 0 before the first refresh
    rows: list[ClassQuestRow]  # by level, then name

    @property
    def missed(self) -> int:
        return sum(row.status == "missed" for row in self.rows)


@dataclass
class ClassQuestRefresh:
    listed: int = 0
    new: list[str] = field(default_factory=list[str])
    errors: list[str] = field(default_factory=list[str])


def key(name: str) -> str:
    """ "Night Elf" -> "night-elf": Forever Companion's class and race names, the same rule
    as classes.class_key (not imported: classes reaches the item pool, which uses this)."""
    return "-".join(name.casefold().split())


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def parse_class_quest(row: Any) -> ClassQuest | None:
    """One `ClassQuest` from GET /class-quests; None without an id, class, name or level."""
    quest_id, class_name, name = (fields.get(row, k) for k in ("id", "class", "name"))
    level = fields.as_int(fields.get(row, "level"))
    if not all(isinstance(v, str) for v in (quest_id, class_name, name)) or level is None:
        return None
    races = fields.get(row, "races")
    faction = fields.get(row, "faction")
    return ClassQuest(
        id=str(quest_id),
        class_key=key(str(class_name)),
        level=level,
        name=str(name),
        faction=faction if isinstance(faction, str) else "both",
        races=[key(r) for r in fields.as_list(races) if isinstance(r, str)]
        if isinstance(races, list)
        else None,
        giver=_text(fields.get(row, "giver")),
        location=_text(fields.get(row, "location")),
        reward=_text(fields.get(row, "reward")),
        essential=fields.get(row, "essential") is True,
    )


def stored_class_quests(session: Session) -> list[ClassQuest]:
    rows = session.exec(select(CompanionClassQuest)).all()
    parsed = (parse_class_quest(row.payload) for row in rows)
    return [q for q in parsed if q is not None]


def refresh_class_quests(session: Session, http: httpx.Client) -> ClassQuestRefresh:
    """Fetch the class quest list and merge each quest into the stored ones, by id."""
    outcome = ClassQuestRefresh()
    try:
        response = http.get(f"{BASE_URL}/class-quests")
    except httpx.HTTPError as error:
        outcome.errors.append(f"class quest list: {error}")
        return outcome
    if response.status_code != 200:
        outcome.errors.append(f"class quest list: HTTP {response.status_code}")
        return outcome
    rows = fields.get(response.json(), "data")
    if not isinstance(rows, list):
        outcome.errors.append("class quest list: unexpected response shape")
        return outcome

    known = {row.quest_id for row in session.exec(select(CompanionClassQuest)).all()}
    now = utcnow()
    for row in fields.as_list(rows):
        quest = parse_class_quest(row)
        if quest is None:
            continue
        outcome.listed += 1
        if quest.id not in known:
            outcome.new.append(quest.id)
        session.merge(CompanionClassQuest(quest_id=quest.id, payload=row, fetched_at=now))
    session.commit()  # one short write: the list is a single request
    logger.info(
        "Forever Companion class quests: %d listed, %d new", outcome.listed, len(outcome.new)
    )
    return outcome


def applies(quest: ClassQuest, class_name: str, faction: str | None, race: str | None) -> bool:
    """Whether this class, faction and race can take the quest. An unknown faction or race
    doesn't rule a quest out."""
    if quest.class_key != key(class_name):
        return False
    if faction is not None and quest.faction not in ("both", faction):
        return False
    return quest.races is None or race is None or key(race) in quest.races


def status(quest: ClassQuest, level: int | None, done: bool) -> Status:
    if done:
        return "done"
    if level is None or quest.level > level + SOON_LEVELS:
        return "later"
    if quest.level > level:
        return "soon"
    return "missed" if quest.essential else "now"


def done_ids(session: Session) -> set[str]:
    return {row.quest_id for row in session.exec(select(ClassQuestDone)).all()}


def checklist(session: Session, character_id: int | None) -> ClassQuestChecklist:
    """The synced character's class quests: missed, now, soon, later or done."""
    snapshots = latest_by_kind(session, character_id)
    character = character_view(snapshots)
    profile = snapshots.get("profile")
    faction = character_faction(profile.payload if profile else None)
    stored = stored_class_quests(session)
    rows: list[ClassQuestRow] = []
    if character.character_class is not None:
        done = done_ids(session)
        rows = [
            ClassQuestRow(
                **quest.model_dump(),
                done=quest.id in done,
                status=status(quest, character.level, quest.id in done),
            )
            for quest in stored
            if applies(quest, character.character_class, faction, character.race)
        ]
    rows.sort(key=lambda r: (r.level, r.name))
    return ClassQuestChecklist(
        class_name=character.character_class,
        level=character.level,
        listed=len(stored),
        rows=rows,
    )


class UnknownClassQuest(LookupError):
    pass


def set_done(session: Session, quest_id: str, done: bool) -> None:
    """Mark a stored class quest done, or not done. Raises UnknownClassQuest for an id
    Forever Companion hasn't listed."""
    if session.get(CompanionClassQuest, quest_id) is None:
        raise UnknownClassQuest(quest_id)
    existing = session.get(ClassQuestDone, quest_id)
    if done and existing is None:
        session.add(ClassQuestDone(quest_id=quest_id))
    elif not done and existing is not None:
        session.delete(existing)
    session.commit()
