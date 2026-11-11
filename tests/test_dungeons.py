import json
from typing import Any

import httpx
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.companion import BASE_URL
from character_planner.dungeons import (
    listed_dungeon_ids,
    parse_dungeon,
    refresh_dungeons,
    stored_dungeons,
)

from .conftest import FIXTURES

HALL = json.loads((FIXTURES / "companion_dungeon_hall_of_thanes.json").read_text(encoding="utf-8"))

DEADMINES: dict[str, Any] = {
    "data": {
        "id": "the-deadmines",
        "name": "The Deadmines",
        "minLevel": 17,
        "maxLevel": 26,
        "status": "launch",
        "loot": [
            {
                "itemId": 5193,
                "name": "Cape of the Brotherhood",
                "slot": "back",
                "quality": "rare",
                "source": "Edwin VanCleef",
            },
            {"itemId": None, "name": "Unmatched Trinket", "slot": "trinket", "quality": None},
        ],
        "quests": [
            {
                "questId": 166,
                "name": "The Defias Brotherhood",
                "level": 22,
                "minLevel": 14,
                "faction": "alliance",
                "rewards": {
                    "items": [
                        {"id": 2041, "name": "Tunic of Westfall"},
                        {"id": 2042, "name": "Staff of Westfall"},
                    ],
                    "choice": True,
                },
            },
            {
                "questId": None,
                "name": "Horde Errand",
                "faction": "horde",
                "rewards": {"items": [{"id": 9999, "name": "Horde Thing"}], "choice": False},
            },
        ],
    },
    "meta": {},
}

LIST = {
    "data": [
        {"id": "hall-of-thanes", "name": "Hall of Thanes", "status": "launch"},
        {"id": "the-deadmines", "name": "The Deadmines", "status": "launch"},
        {"id": "shapers-terrace", "name": "Shaper's Terrace", "status": "announced"},
    ],
    "meta": {},
}


def mock_companion_dungeons() -> respx.Route:
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(200, json=LIST))
    respx.get(f"{BASE_URL}/dungeons/hall-of-thanes").mock(
        return_value=httpx.Response(200, json=HALL)
    )
    return respx.get(f"{BASE_URL}/dungeons/the-deadmines").mock(
        return_value=httpx.Response(200, json=DEADMINES)
    )


def test_parse_hall_of_thanes_drop_table() -> None:
    dungeon = parse_dungeon(HALL)
    assert dungeon is not None
    assert dungeon.id == "hall-of-thanes"
    by_id = {loot.item_id: loot for loot in dungeon.loot}
    assert by_id[271098].name == "Golemguard Chest"
    assert by_id[271098].boss == "Plunder"
    assert by_id[271097].slot == "back"
    assert by_id[270256].quality == "RARE"


def test_parse_quest_rewards_and_skips_loot_without_an_id() -> None:
    dungeon = parse_dungeon(DEADMINES)
    assert dungeon is not None
    assert [loot.item_id for loot in dungeon.loot] == [5193]
    tunic, staff, horde = dungeon.rewards
    assert (tunic.item_id, tunic.quest, tunic.faction, tunic.choice) == (
        2041,
        "The Defias Brotherhood",
        "alliance",
        True,
    )
    assert staff.item_id == 2042
    assert horde.faction == "horde"
    assert parse_dungeon({"data": {"name": "no id"}}) is None


def test_listed_ids_skip_announced_dungeons() -> None:
    assert listed_dungeon_ids(LIST) == ["hall-of-thanes", "the-deadmines"]
    assert listed_dungeon_ids("Not Found") == []


@respx.mock
def test_refresh_stores_dungeons_and_skips_fresh_ones(engine: Engine) -> None:
    deadmines = mock_companion_dungeons()
    with Session(engine) as session, httpx.Client() as http:
        first = refresh_dungeons(session, http, pause=0)
        assert first.listed == 2
        assert sorted(first.fetched) == ["hall-of-thanes", "the-deadmines"]
        assert {d.id for d in stored_dungeons(session)} == {"hall-of-thanes", "the-deadmines"}

        assert refresh_dungeons(session, http, pause=0).fetched == []  # cached
        assert len(refresh_dungeons(session, http, pause=0, force=True).fetched) == 2
    assert deadmines.call_count == 2


@respx.mock
def test_refresh_stops_on_rate_limit(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(200, json=LIST))
    detail = respx.get(url__startswith=f"{BASE_URL}/dungeons/").mock(
        return_value=httpx.Response(429)
    )
    with Session(engine) as session, httpx.Client() as http:
        outcome = refresh_dungeons(session, http, pause=0)
    assert detail.call_count == 1
    assert outcome.fetched == []
    assert "rate limited" in outcome.errors[0]


@respx.mock
def test_refresh_reports_a_failed_list(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(503))
    with Session(engine) as session, httpx.Client() as http:
        outcome = refresh_dungeons(session, http, pause=0)
    assert outcome.errors == ["dungeon list: HTTP 503"]
