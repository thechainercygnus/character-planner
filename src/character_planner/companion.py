"""Forever Companion item source, looked up by item id only (ADR 0004).

https://forevercompanion.io: a free, keyless fan API (120 requests/min per IP). Its
OpenAPI spec is vendored at docs/vendor/forevercompanion-openapi.json.

Only GET /items/{id} is used. The list endpoint (/items?q=..., ids, limit, offset) is
served from a Netlify cache keyed on the path alone, so it returns whatever list was
cached last regardless of the query (seen 2026-11-11). Per-id paths aren't affected.

Using this data requires linking back to Forever Companion and crediting its sources;
see ATTRIBUTION.
"""

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.db import CompanionItem, utcnow

BASE_URL = "https://forevercompanion.io/api/v1"
USER_AGENT = "character-planner/0.1 (personal WoW Forever planner)"
ATTRIBUTION = {
    "name": "Forever Companion",
    "url": "https://forevercompanion.io",
    "text": (
        "Item data from Forever Companion, gathered from ForeverChanges, Wowhead and Zockify "
        "and checked in game by players. Fan-made, not affiliated with Blizzard Entertainment."
    ),
}
WOWHEAD_ICON = "https://wow.zamimg.com/images/wow/icons/medium/{icon}.jpg"
MAX_AGE = timedelta(hours=24)

_ARMOR_LINE = re.compile(r"^(\d+) Armor$")
_STAT_LINE = re.compile(r"^\+(\d+) ([A-Za-z][A-Za-z ]*)$")
_DPS_LINE = re.compile(r"^\(([\d.]+) damage per second\)$")


class CompanionInfo(BaseModel):
    item_id: int
    name: str | None = None
    item_level: int | None = None
    required_level: int | None = None
    quality: str | None = None  # uppercased to match Blizzard: UNCOMMON, RARE...
    slot: str | None = None  # Head, One-Hand, Held In Off-hand...
    weapon_type: str | None = None  # Axe, Shield, Wand... (None for armor and jewelry)
    armor_type: str | None = None  # Cloth, Leather, Mail, Plate, or the tooltip's type
    armor: int | None = None
    stats: dict[str, int] = {}
    dps: float | None = None
    drops: list[str] = []
    rewards: list[str] = []
    verified: int | None = None
    classic_only: bool | None = None
    icon_url: str | None = None
    wowhead: str | None = None


@dataclass
class CompanionRefresh:
    fetched: list[int] = field(default_factory=list)
    not_found: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_item(payload: Any) -> CompanionInfo | None:
    """Turn a GET /items/{id} body (or its `data`) into CompanionInfo."""
    item = fields.get(payload, "data") if isinstance(fields.get(payload, "data"), dict) else payload
    item_id = fields.as_int(fields.get(item, "id"))
    if item_id is None:
        return None

    armor: int | None = None
    bonus_armor = 0
    dps: float | None = None
    stats: dict[str, int] = {}
    tooltip_armor_type: str | None = None
    for line in fields.get(item, "tooltip") or []:
        left = fields.get(line, "left")
        right = fields.get(line, "right")
        if not isinstance(left, str):
            continue
        if (match := _ARMOR_LINE.match(left.strip())) is not None:
            armor = int(match.group(1))
        elif (match := _DPS_LINE.match(left.strip())) is not None:
            dps = float(match.group(1))
        elif (match := _STAT_LINE.match(left.strip())) is not None:
            name, value = match.group(2).strip(), int(match.group(1))
            if name == "Armor":  # "+50 Armor" is bonus armor, part of the item's total
                bonus_armor += value
            else:
                stats[name] = value
        elif isinstance(right, str) and left == fields.get(item, "slot"):
            tooltip_armor_type = right  # "Waist | Mail", "Off Hand | Shield"

    if bonus_armor:
        armor = (armor or 0) + bonus_armor
    armor_class = fields.get(item, "armor")
    quality = fields.get(item, "quality")
    icon = fields.get(item, "icon")
    return CompanionInfo(
        item_id=item_id,
        name=fields.get(item, "name"),
        item_level=fields.as_int(fields.get(item, "itemLevel")),
        required_level=fields.as_int(fields.get(item, "requiredLevel")),
        quality=quality.upper() if isinstance(quality, str) else None,
        slot=fields.get(item, "slot"),
        weapon_type=fields.get(item, "weaponType"),
        armor_type=armor_class.capitalize() if isinstance(armor_class, str) else tooltip_armor_type,
        armor=armor,
        stats=stats,
        dps=dps,
        drops=[
            f"{fields.get(d, 'dungeon', 'name')} - {fields.get(d, 'source')}"
            if fields.get(d, "source")
            else str(fields.get(d, "dungeon", "name"))
            for d in fields.get(item, "dropsFrom") or []
        ],
        rewards=[
            f"Quest: {fields.get(r, 'name')}"
            for r in fields.get(item, "rewardFrom") or []
            if fields.get(r, "name")
        ],
        verified=fields.as_int(fields.get(item, "verified")),
        classic_only=fields.get(item, "classicOnly"),
        icon_url=WOWHEAD_ICON.format(icon=icon) if isinstance(icon, str) and icon else None,
        wowhead=fields.get(item, "wowhead"),
    )


def companion_by_id(session: Session) -> dict[int, CompanionInfo]:
    infos: dict[int, CompanionInfo] = {}
    for row in session.exec(select(CompanionItem)).all():
        if row.found and (info := parse_item(row.payload)) is not None:
            infos[row.item_id] = info
    return infos


def fetch_item(http: httpx.Client, item_id: int) -> httpx.Response:
    return http.get(f"{BASE_URL}/items/{item_id}")


def refresh_companion(
    session: Session,
    item_ids: Iterable[int],
    *,
    force: bool = False,
    http: httpx.Client | None = None,
    max_age: timedelta = MAX_AGE,
    pause: float = 0.0,
    progress: Callable[[str], None] | None = None,
) -> CompanionRefresh:
    """Fetch items not cached within max_age (all of them with force).

    pause sleeps between requests, for long batches (the item pool). Stops at the first
    429 so a batch never hammers the rate limit; the rest are tried on the next refresh.
    """
    outcome = CompanionRefresh()
    cutoff = utcnow() - max_age
    cached = {row.item_id: row for row in session.exec(select(CompanionItem)).all()}
    wanted = [
        item_id
        for item_id in dict.fromkeys(item_ids)
        if force or item_id not in cached or as_utc(cached[item_id].fetched_at) < cutoff
    ]

    own_http = http is None
    client = http or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
    try:
        for index, item_id in enumerate(wanted, start=1):
            if pause and index > 1:
                time.sleep(pause)
            if progress:
                progress(f"item {index}/{len(wanted)}: {item_id}")
            try:
                response = fetch_item(client, item_id)
            except httpx.HTTPError as error:
                outcome.errors.append(f"{item_id}: {error}")
                continue
            if response.status_code == 429:
                outcome.errors.append(f"{item_id}: rate limited; stopping this batch")
                break
            if response.status_code == 404:
                session.merge(CompanionItem(item_id=item_id, found=False, fetched_at=utcnow()))
                outcome.not_found.append(item_id)
                continue
            if response.status_code != 200:
                outcome.errors.append(f"{item_id}: HTTP {response.status_code}")
                continue
            body = response.json()
            if parse_item(body) is None:
                outcome.errors.append(f"{item_id}: unexpected response shape")
                continue
            session.merge(
                CompanionItem(item_id=item_id, found=True, payload=body, fetched_at=utcnow())
            )
            outcome.fetched.append(item_id)
        session.commit()
    finally:
        if own_http:
            client.close()
    return outcome


def as_utc(moment: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone; they were stored as UTC.
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
