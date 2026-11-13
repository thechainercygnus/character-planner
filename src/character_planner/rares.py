"""Forever Companion rares: rare spawns and their drops, a third item pool source (#6,
ADR 0029).

GET /rares is unpaged, but its CDN cache is keyed on the path alone (ADR 0004), so it
returns whatever list was cached last, filtered or not: on 2026-11-13 one request got
another client's `?zone=The Barrens` result (3 rares), the next the full list (28). A
filtered list is always a subset of the full one, so each rare is stored by its id and
every fetch is merged in, never replacing what's stored. The stored set only grows toward
the full list; a rare Forever Companion drops stays until it reappears changed.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.companion import BASE_URL
from character_planner.db import CompanionRare, utcnow
from character_planner.dungeons import Loot, parse_loot

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"\d+")


class Rare(BaseModel):
    id: str
    name: str
    zone: str | None = None
    min_level: int | None = None
    max_level: int | None = None
    faction: str = "both"  # alliance, horde or both
    spawns: int = 0  # spawn points listed
    elite: bool = False
    loot: list[Loot] = []


@dataclass
class RareRefresh:
    listed: int = 0
    new: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_levels(value: Any) -> tuple[int | None, int | None]:
    """`levels` as (lowest, highest). The spec says "24" or "24-25"; real responses put
    an en dash between the two, so any separator is accepted."""
    numbers = [int(n) for n in _NUMBER.findall(value)] if isinstance(value, str) else []
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def parse_rare(row: Any) -> Rare | None:
    """One `Rare` from GET /rares."""
    rare_id = fields.get(row, "id")
    name = fields.get(row, "name")
    if not isinstance(rare_id, str) or not isinstance(name, str):
        return None
    low, high = parse_levels(fields.get(row, "levels"))
    zone = fields.get(row, "zone")
    faction = fields.get(row, "faction")
    coords = fields.get(row, "coords")
    return Rare(
        id=rare_id,
        name=name,
        zone=zone if isinstance(zone, str) else None,
        min_level=low,
        max_level=high,
        faction=faction if isinstance(faction, str) else "both",
        spawns=len(coords) if isinstance(coords, list) else 0,
        elite=fields.get(row, "elite") is True,
        loot=parse_loot(fields.get(row, "loot")),
    )


def stored_rares(session: Session) -> list[Rare]:
    parsed = (parse_rare(row.payload) for row in session.exec(select(CompanionRare)).all())
    return sorted((r for r in parsed if r is not None), key=lambda r: r.id)


def refresh_rares(session: Session, http: httpx.Client) -> RareRefresh:
    """Fetch the rare list and merge each rare into the stored ones, by id."""
    outcome = RareRefresh()
    try:
        response = http.get(f"{BASE_URL}/rares")
    except httpx.HTTPError as error:
        outcome.errors.append(f"rare list: {error}")
        return outcome
    if response.status_code != 200:
        outcome.errors.append(f"rare list: HTTP {response.status_code}")
        return outcome
    rows = fields.get(response.json(), "data")
    if not isinstance(rows, list):
        outcome.errors.append("rare list: unexpected response shape")
        return outcome

    known = {row.rare_id for row in session.exec(select(CompanionRare)).all()}
    now = utcnow()
    for row in rows:
        rare = parse_rare(row)
        if rare is None:
            continue
        outcome.listed += 1
        if rare.id not in known:
            outcome.new.append(rare.id)
        session.merge(CompanionRare(rare_id=rare.id, payload=row, fetched_at=now))
    session.commit()  # one short write: the list is a single request
    logger.info(
        "Forever Companion rares: %d listed, %d new, %d stored",
        outcome.listed,
        len(outcome.new),
        len(known) + len(outcome.new),
    )
    return outcome
