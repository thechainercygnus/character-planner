"""Quest chains for quest-reward upgrades (#7, ADR 0028).

A dungeon quest's `prerequisites` (Forever Companion) list the whole chain before it,
earliest first; each step holds the quests done side by side, as `{ questId, name }`.
So the chain itself needs no more requests. A step's giver, location and level do:

- a step that is itself a dungeon quest is described in the stored dungeon data;
- GET /quests/{questId} serves only dungeon and elite (group) quests. Ordinary zone
  quests answer 404 (probed 2026-11-13: 91 of the 103 steps outside dungeon data), so
  404s are cached like items' (found=False) and those steps show their name and a
  Wowhead link.
"""

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.companion import BASE_URL, USER_AGENT, as_utc
from character_planner.db import CompanionQuest, save_now, utcnow
from character_planner.logs import JobLog

logger = logging.getLogger(__name__)

# Quest data rarely changes, and a zone quest's 404 won't often turn into a 200.
QUEST_MAX_AGE = timedelta(days=7)
# Every quest link in Forever Companion's data has this form (dungeon and elite quests);
# steps it can't describe link there too.
WOWHEAD_QUEST = "https://www.wowhead.com/forever/quest={quest_id}"


class QuestStep(BaseModel):
    """One quest in a chain. Only quest_id and name are always known."""

    quest_id: int | None = None
    name: str
    level: int | None = None
    min_level: int | None = None  # level needed to pick it up
    giver: str | None = None
    location: str | None = None  # where the giver is (dungeon quests)
    zone: str | None = None  # the quest's zone (elite quests)
    dungeon: str | None = None  # the dungeon it's done in (dungeon quests)
    wowhead: str | None = None
    known: bool = False  # described by Forever Companion, not just named

    @property
    def start_level(self) -> int | None:
        return self.min_level if self.min_level is not None else self.level


ChainRefs = list[list[tuple[int | None, str]]]


@dataclass
class QuestRefresh:
    fetched: list[int] = field(default_factory=list)
    not_found: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _data(payload: Any) -> Any:
    inner = fields.get(payload, "data")
    return inner if inner is not None else payload


def parse_quest(payload: Any) -> QuestStep | None:
    """A Quest object (a dungeon's quest, or a GET /quests/{id} body) as a QuestStep."""
    quest = _data(payload)
    name = fields.get(quest, "name")
    if not isinstance(name, str):
        return None
    quest_id = fields.as_int(fields.get(quest, "questId"))
    dungeon = fields.get(quest, "dungeon", "name")
    wowhead = fields.get(quest, "wowhead")
    return QuestStep(
        quest_id=quest_id,
        name=name,
        level=fields.as_int(fields.get(quest, "level")),
        min_level=fields.as_int(fields.get(quest, "minLevel")),
        giver=_text(fields.get(quest, "giver")),
        location=_text(fields.get(quest, "location")),
        zone=_text(fields.get(quest, "zone")),
        dungeon=_text(dungeon),
        wowhead=_text(wowhead) or _wowhead(quest_id),
        known=True,
    )


def parse_prerequisites(value: Any) -> ChainRefs:
    """A quest's `prerequisites` as steps of (quest id, name); malformed entries dropped."""
    steps: ChainRefs = []
    for step in value if isinstance(value, list) else []:
        quests = [
            (fields.as_int(fields.get(ref, "questId")), name)
            for ref in (step if isinstance(step, list) else [])
            if isinstance(name := fields.get(ref, "name"), str)
        ]
        if quests:
            steps.append(quests)
    return steps


def chain_steps(refs: ChainRefs, known: Mapping[int, QuestStep]) -> list[list[QuestStep]]:
    """The chain with each step described where Forever Companion knows it."""
    return [
        [
            known[quest_id]
            if quest_id is not None and quest_id in known
            else QuestStep(quest_id=quest_id, name=name, wowhead=_wowhead(quest_id))
            for quest_id, name in step
        ]
        for step in refs
    ]


def chain_level(chain: Iterable[Iterable[QuestStep]]) -> int | None:
    """The highest level any step needs to be picked up, where known."""
    levels = [s.start_level for step in chain for s in step if s.start_level is not None]
    return max(levels, default=None)


def stored_quests(session: Session) -> dict[int, QuestStep]:
    """Quests fetched by id, keyed by quest id (found ones only)."""
    quests: dict[int, QuestStep] = {}
    for row in session.exec(select(CompanionQuest)).all():
        if row.found and (quest := parse_quest(row.payload)) is not None:
            quests[row.quest_id] = quest
    return quests


def refresh_quests(
    session: Session,
    quest_ids: Iterable[int],
    *,
    http: httpx.Client | None = None,
    force: bool = False,
    max_age: timedelta = QUEST_MAX_AGE,
    pause: float = 0.0,
    progress: Callable[[str], None] | None = None,
) -> QuestRefresh:
    """Fetch quests not cached within max_age, a 404 included. Stops at the first 429,
    as the item and dungeon batches do."""
    outcome = QuestRefresh()
    cutoff = utcnow() - max_age
    cached = {row.quest_id: row for row in session.exec(select(CompanionQuest)).all()}
    wanted = [
        quest_id
        for quest_id in dict.fromkeys(quest_ids)
        if force or quest_id not in cached or as_utc(cached[quest_id].fetched_at) < cutoff
    ]
    if not wanted:
        return outcome

    own_http = http is None
    client = http or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
    job = JobLog(logger, "Forever Companion quest chain steps", len(wanted))
    try:
        for index, quest_id in enumerate(wanted, start=1):
            job.step(index)
            if pause and index > 1:
                time.sleep(pause)
            if progress:
                progress(f"quest {index}/{len(wanted)}: {quest_id}")
            try:
                response = client.get(f"{BASE_URL}/quests/{quest_id}")
            except httpx.HTTPError as error:
                outcome.errors.append(f"quest {quest_id}: {error}")
                continue
            if response.status_code == 429:
                outcome.errors.append(f"quest {quest_id}: rate limited; stopping this batch")
                break
            if response.status_code == 404:
                save_now(
                    session, CompanionQuest(quest_id=quest_id, found=False, fetched_at=utcnow())
                )
                outcome.not_found.append(quest_id)
                continue
            if response.status_code != 200:
                outcome.errors.append(f"quest {quest_id}: HTTP {response.status_code}")
                continue
            body = response.json()
            if parse_quest(body) is None:
                outcome.errors.append(f"quest {quest_id}: unexpected response shape")
                continue
            save_now(
                session,
                CompanionQuest(quest_id=quest_id, found=True, payload=body, fetched_at=utcnow()),
            )
            outcome.fetched.append(quest_id)
    finally:
        if own_http:
            client.close()
    job.done(
        f"{len(outcome.fetched)} fetched, {len(outcome.not_found)} not described "
        f"(zone quests), {len(outcome.errors)} errors",
        outcome.errors,
    )
    return outcome


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _wowhead(quest_id: int | None) -> str | None:
    return WOWHEAD_QUEST.format(quest_id=quest_id) if quest_id is not None else None
