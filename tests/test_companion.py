import json
from datetime import timedelta
from typing import Any

import httpx
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.companion import (
    BASE_URL,
    companion_by_id,
    parse_item,
    refresh_companion,
)
from character_planner.db import CompanionItem, utcnow

from .conftest import FIXTURES


def girdle() -> Any:
    """Real GET /items/270230 response (Kindlegem Girdle), captured 2026-11-11."""
    return json.loads((FIXTURES / "companion_item_270230.json").read_text(encoding="utf-8"))


# Built from the observed /items/5193 response (fields per the vendored OpenAPI spec);
# the dungeon name wasn't printed in that run, so it is illustrative.
CAPE = {
    "data": {
        "id": 5193,
        "name": "Cape of the Brotherhood",
        "quality": "uncommon",
        "icon": "inv_misc_cape_10",
        "itemLevel": 24,
        "requiredLevel": 19,
        "slot": "Back",
        "armor": None,
        "tooltip": [
            {"left": "Binds when picked up", "kind": "plain"},
            {"left": "Back", "kind": "plain"},
            {"left": "21 Armor", "kind": "plain"},
            {"left": "+5 Agility", "kind": "plain"},
            {"left": "+3 Stamina", "kind": "plain"},
            {"left": "Requires Level 19", "kind": "plain"},
        ],
        "dropsFrom": [
            {"dungeon": {"id": "deadmines", "name": "The Deadmines"}, "source": "Edwin VanCleef"}
        ],
        "rewardFrom": [],
    }
}


def test_parse_real_item_reads_tooltip_numbers() -> None:
    info = parse_item(girdle())
    assert info is not None
    assert (info.item_id, info.name, info.item_level) == (270230, "Kindlegem Girdle", 18)
    assert (info.armor_type, info.armor, info.quality) == ("Mail", 100, "RARE")
    assert info.stats == {"Stamina": 7}
    assert info.icon_url == "https://wow.zamimg.com/images/wow/icons/medium/inv_belt_20.jpg"
    assert info.wowhead == "https://www.wowhead.com/forever/item=270230"


def test_parse_drop_sources_and_items_without_an_armor_class() -> None:
    info = parse_item(CAPE)
    assert info is not None
    assert info.armor_type is None  # cloaks have no armor class
    assert info.armor == 21
    assert info.stats == {"Agility": 5, "Stamina": 3}
    assert info.drops == ["The Deadmines - Edwin VanCleef"]


def test_parse_rejects_unexpected_shapes() -> None:
    assert parse_item({"error": "Not found"}) is None
    assert parse_item("oops") is None


@respx.mock
def test_refresh_stores_found_and_missing_items(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/items/270230").mock(return_value=httpx.Response(200, json=girdle()))
    respx.get(f"{BASE_URL}/items/999").mock(return_value=httpx.Response(404, json={}))
    with Session(engine) as session:
        outcome = refresh_companion(session, [270230, 999])
        infos = companion_by_id(session)

    assert (outcome.fetched, outcome.not_found, outcome.errors) == ([270230], [999], [])
    assert set(infos) == {270230}


@respx.mock
def test_refresh_skips_fresh_items_and_refetches_stale_or_forced(engine: Engine) -> None:
    route = respx.get(f"{BASE_URL}/items/270230").mock(
        return_value=httpx.Response(200, json=girdle())
    )
    with Session(engine) as session:
        refresh_companion(session, [270230])
        assert refresh_companion(session, [270230]).fetched == []  # fresh: skipped
        assert refresh_companion(session, [270230], force=True).fetched == [270230]

        row = session.get(CompanionItem, 270230)
        assert row is not None
        row.fetched_at = utcnow() - timedelta(hours=25)
        session.add(row)
        session.commit()
        assert refresh_companion(session, [270230]).fetched == [270230]  # stale
    assert route.call_count == 3


@respx.mock
def test_refresh_stops_at_rate_limit(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/items/1").mock(return_value=httpx.Response(429))
    later = respx.get(f"{BASE_URL}/items/2").mock(return_value=httpx.Response(200, json=CAPE))
    with Session(engine) as session:
        outcome = refresh_companion(session, [1, 2])

    assert "rate limited" in outcome.errors[0]
    assert not later.called
