"""Forever Companion dungeons: drop tables and dungeon quest rewards (ADR 0006).

GET /dungeons lists every dungeon and has no paging, so the CDN cache that ignores
query strings (ADR 0004) doesn't matter: the unfiltered list is the whole list.
GET /dungeons/{id} carries the dungeon's drop table (item ids, slot, quality, boss) and
its quests with reward item ids. Both are cached here as raw payloads (ADR 0002).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields, upstream
from character_planner.companion import BASE_URL, USER_AGENT, as_utc
from character_planner.db import CompanionDungeon, save_now, utcnow
from character_planner.logs import JobLog
from character_planner.quests import ChainRefs, QuestStep, parse_prerequisites, parse_quest

logger = logging.getLogger(__name__)

DUNGEON_MAX_AGE = timedelta(hours=24)
# Forever Companion allows 120 requests/min per IP; this keeps a long batch under it.
REQUEST_PAUSE = 0.55

Progress = Callable[[str], None]


class Loot(BaseModel):
    item_id: int
    name: str
    slot: str | None = None  # Forever Companion's slot words: wrist, main-hand, staff...
    quality: str | None = None  # uppercased to match Blizzard: RARE...
    boss: str | None = None


class QuestReward(BaseModel):
    item_id: int
    name: str
    quest: str
    quest_id: int | None = None
    level: int | None = None
    min_level: int | None = None
    faction: str = "both"  # alliance, horde or both
    choice: bool = False  # one of several rewards to pick from
    # The quests to do first, earliest first: (quest id, name) side by side per step (#7).
    prerequisites: ChainRefs = []


class Dungeon(BaseModel):
    id: str
    name: str
    min_level: int | None = None
    max_level: int | None = None
    status: str | None = None  # launch or announced
    zone: str | None = None
    # alliance or horde: the entrance is in a capital the other side can't reach (#4).
    access: str | None = None
    beta_locked: bool = False  # "not open in the beta yet"
    loot: list[Loot] = []
    rewards: list[QuestReward] = []
    # Every quest it lists, described: chain steps found here need no request (#7).
    quests: list[QuestStep] = []


@dataclass
class DungeonRefresh:
    listed: int = 0
    fetched: list[str] = field(default_factory=list[str])
    errors: list[str] = field(default_factory=list[str])


def _data(payload: Any) -> Any:
    inner = fields.get(payload, "data")
    return inner if inner is not None else payload


def _describe(response: httpx.Response) -> str:
    """Enough of an unexpected response to diagnose it, without dumping the body."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}, not JSON ({len(response.content)} bytes)"
    data = _data(body)
    keys = sorted(fields.as_mapping(body))[:8] if isinstance(body, dict) else type(body).__name__
    size = (
        len(fields.as_list(data) or fields.as_mapping(data))
        if isinstance(data, list | dict)
        else type(data).__name__
    )
    return f"HTTP {response.status_code}, top-level keys {keys}, data size {size}"


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _upper(value: Any) -> str | None:
    return value.upper() if isinstance(value, str) else None


def parse_loot(rows: Any) -> list[Loot]:
    """A `Loot` list (a dungeon's drop table, a rare's drops); rows without an item id
    are left out."""
    return [
        Loot(
            item_id=item_id,
            name=str(fields.get(row, "name") or item_id),
            slot=fields.get(row, "slot"),
            quality=_upper(fields.get(row, "quality")),
            boss=fields.get(row, "source"),
        )
        for row in fields.as_list(rows)
        if (item_id := fields.as_int(fields.get(row, "itemId"))) is not None
    ]


def parse_dungeon(payload: Any) -> Dungeon | None:
    """Turn a GET /dungeons/{id} body (or its `data`) into a Dungeon."""
    data = _data(payload)
    dungeon_id = fields.get(data, "id")
    name = fields.get(data, "name")
    if not isinstance(dungeon_id, str) or not isinstance(name, str):
        return None

    loot = parse_loot(fields.get(data, "loot"))

    rewards: list[QuestReward] = []
    quests: list[QuestStep] = []
    for quest in fields.as_list(fields.get(data, "quests")):
        quest_name = fields.get(quest, "name")
        if not isinstance(quest_name, str):
            continue
        if (step := parse_quest(quest)) is not None:
            quests.append(step)
        prerequisites = parse_prerequisites(fields.get(quest, "prerequisites"))
        faction = fields.get(quest, "faction")
        for item in fields.as_list(fields.get(quest, "rewards", "items")):
            item_id = fields.as_int(fields.get(item, "id"))
            if item_id is None:
                continue
            rewards.append(
                QuestReward(
                    item_id=item_id,
                    name=str(fields.get(item, "name") or item_id),
                    quest=quest_name,
                    quest_id=fields.as_int(fields.get(quest, "questId")),
                    level=fields.as_int(fields.get(quest, "level")),
                    min_level=fields.as_int(fields.get(quest, "minLevel")),
                    faction=faction if isinstance(faction, str) else "both",
                    choice=fields.get(quest, "rewards", "choice") is True,
                    prerequisites=prerequisites,
                )
            )

    return Dungeon(
        id=dungeon_id,
        name=name,
        min_level=fields.as_int(fields.get(data, "minLevel")),
        max_level=fields.as_int(fields.get(data, "maxLevel")),
        status=fields.get(data, "status"),
        zone=_text(fields.get(data, "zone")),
        access=_text(fields.get(data, "access")),
        beta_locked=fields.get(data, "betaLocked") is True,
        loot=loot,
        rewards=rewards,
        quests=quests,
    )


def listed_dungeon_ids(payload: Any) -> list[str]:
    """Ids from GET /dungeons, skipping dungeons only announced, not in the game yet."""
    rows = _data(payload)
    if not isinstance(rows, list):
        return []
    return [
        dungeon_id
        for row in fields.as_list(rows)
        if isinstance(dungeon_id := fields.get(row, "id"), str)
        and fields.get(row, "status") != "announced"
    ]


def stored_dungeons(session: Session) -> list[Dungeon]:
    parsed = (parse_dungeon(row.payload) for row in session.exec(select(CompanionDungeon)).all())
    return [d for d in parsed if d is not None]


def refresh_dungeons(
    session: Session,
    http: httpx.Client,
    *,
    force: bool = False,
    pause: float = REQUEST_PAUSE,
    progress: Progress | None = None,
) -> DungeonRefresh:
    """Fetch the dungeon list, then each dungeon not cached in the last 24 hours.

    Stops at the first 429 so the batch never hammers the rate limit.
    """
    outcome = DungeonRefresh()
    ids: list[str] = []
    for attempt in (1, 2):
        try:
            response = http.get(f"{BASE_URL}/dungeons")
        except httpx.HTTPError as error:
            outcome.errors.append(f"dungeon list: {error}")
            logger.warning("Forever Companion dungeon list: %s", error)
            return outcome
        if response.status_code != 200:
            outcome.errors.append(f"dungeon list: HTTP {response.status_code}")
            logger.warning("Forever Companion dungeon list: HTTP %s", response.status_code)
            return outcome
        ids = listed_dungeon_ids(response.json())
        if ids:
            break
        # Seen once on a fresh instance (#87): a 200 with no dungeons, and 30 a few minutes
        # later. Say what came back, then try once more after a pause.
        logger.warning(
            "Forever Companion dungeon list came back empty (attempt %d): %s",
            attempt,
            _describe(response),
        )
        if attempt == 1:
            time.sleep(pause * 10)
    if not ids:
        outcome.errors.append("dungeon list: empty response from Forever Companion")
        return outcome
    outcome.listed = len(ids)

    cutoff = utcnow() - DUNGEON_MAX_AGE
    cached = {row.dungeon_id: row for row in session.exec(select(CompanionDungeon)).all()}
    wanted = [d for d in ids if force or d not in cached or as_utc(cached[d].fetched_at) < cutoff]
    job = JobLog(logger, f"Forever Companion dungeons ({len(ids)} listed)", len(wanted))
    for index, dungeon_id in enumerate(wanted, start=1):
        job.step(index)
        time.sleep(pause)
        if progress:
            progress(f"dungeon {index}/{len(wanted)}: {dungeon_id}")
        try:
            detail = http.get(f"{BASE_URL}/dungeons/{dungeon_id}")
        except httpx.HTTPError as error:
            outcome.errors.append(f"{dungeon_id}: {error}")
            continue
        if detail.status_code == 429:
            outcome.errors.append(f"{dungeon_id}: rate limited; stopping this batch")
            break
        if detail.status_code != 200:
            outcome.errors.append(f"{dungeon_id}: HTTP {detail.status_code}")
            continue
        body = detail.json()
        if parse_dungeon(body) is None:
            outcome.errors.append(f"{dungeon_id}: unexpected response shape")
            continue
        save_now(
            session, CompanionDungeon(dungeon_id=dungeon_id, payload=body, fetched_at=utcnow())
        )
        outcome.fetched.append(dungeon_id)
    job.done(f"{len(outcome.fetched)} fetched, {len(outcome.errors)} errors", outcome.errors)
    return outcome


def new_client() -> httpx.Client:
    return upstream.client(headers={"User-Agent": USER_AGENT})
