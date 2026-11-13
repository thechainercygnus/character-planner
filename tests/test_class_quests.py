"""The class quest checklist (#8, ADR 0030)."""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.class_quests import (
    ClassQuest,
    applies,
    parse_class_quest,
    refresh_class_quests,
    status,
    stored_class_quests,
)
from character_planner.companion import BASE_URL

from .conftest import FIXTURES
from .test_app import client, fixture  # noqa: F401 (the client fixture)

# The real GET /class-quests response (2026-11-13): 44 quests, 9 classes.
LIST = json.loads((FIXTURES / "companion_class_quests.json").read_text(encoding="utf-8"))
# What the cache serves for `?class=warrior` when that was cached last (ADR 0004, 0029).
WARRIOR_ONLY = {"data": [q for q in LIST["data"] if q["class"] == "warrior"]}


def quest(quest_id: str) -> ClassQuest:
    parsed = parse_class_quest(next(q for q in LIST["data"] if q["id"] == quest_id))
    assert parsed is not None
    return parsed


def test_every_real_class_quest_parses() -> None:
    parsed = [parse_class_quest(q) for q in LIST["data"]]
    assert len(parsed) == 44 and all(q is not None for q in parsed)
    muren = quest("warrior-defensive-stance-dwarf")
    assert (muren.class_key, muren.level, muren.name, muren.faction) == (
        "warrior",
        10,
        "Muren Stormpike",
        "alliance",
    )
    assert (muren.races, muren.giver, muren.location, muren.essential) == (
        ["dwarf", "gnome"],
        "Muren Stormpike",
        "Dun Morogh",
        True,
    )
    assert muren.reward == "Defensive Stance, Taunt, Sunder Armor and a weapon"
    assert quest("warrior-fire-hardened").location is None
    assert parse_class_quest({"id": "x", "class": "warrior", "name": "No level"}) is None


def test_a_gnome_warrior_gets_the_gnome_and_alliance_quests() -> None:
    every = [q for q in (parse_class_quest(r) for r in LIST["data"]) if q is not None]
    mine = [q.id for q in every if applies(q, "Warrior", "alliance", "Gnome")]
    assert mine == [
        "warrior-defensive-stance-dwarf",  # dwarves and gnomes, not humans or night elves
        "warrior-fire-hardened",  # alliance; the horde's Brutal Armor is left out
        "warrior-berserker-stance",  # both factions
    ]


def test_race_names_match_blizzards() -> None:
    assert applies(quest("warrior-defensive-stance-nelf"), "Warrior", "alliance", "Night Elf")
    assert not applies(quest("warrior-defensive-stance-nelf"), "Warrior", "alliance", "Gnome")
    assert not applies(quest("warrior-defensive-stance-dwarf"), "Warlock", "alliance", "Gnome")


def test_an_unknown_faction_or_race_rules_nothing_out() -> None:
    assert applies(quest("warrior-brutal-armor"), "Warrior", None, None)
    assert applies(quest("warrior-defensive-stance-undead"), "Warrior", "horde", None)


@pytest.mark.parametrize(
    ("quest_id", "level", "done", "expected"),
    [
        ("warrior-defensive-stance-dwarf", 18, False, "missed"),  # essential, level 10
        ("warrior-defensive-stance-dwarf", 18, True, "done"),
        ("warrior-defensive-stance-dwarf", 10, False, "missed"),  # at its level
        ("warrior-fire-hardened", 20, False, "now"),  # not essential: never missed
        ("warrior-fire-hardened", 18, False, "soon"),  # level 20: within 5 levels
        ("warrior-fire-hardened", 15, False, "soon"),
        ("warrior-berserker-stance", 18, False, "later"),  # level 30
        ("warrior-berserker-stance", None, False, "later"),  # no level synced
    ],
)
def test_status(quest_id: str, level: int | None, done: bool, expected: str) -> None:
    assert status(quest(quest_id), level, done) == expected


@respx.mock
def test_a_filtered_list_never_removes_class_quests(engine: Engine) -> None:
    route = respx.get(f"{BASE_URL}/class-quests")
    with Session(engine) as session, httpx.Client() as http:
        route.mock(return_value=httpx.Response(200, json=WARRIOR_ONLY))
        first = refresh_class_quests(session, http)
        route.mock(return_value=httpx.Response(200, json=LIST))
        full = refresh_class_quests(session, http)
        route.mock(return_value=httpx.Response(200, json=WARRIOR_ONLY))
        again = refresh_class_quests(session, http)
        stored = stored_class_quests(session)

    assert (first.listed, len(first.new)) == (8, 8)
    assert (full.listed, len(full.new)) == (44, 36)
    assert (again.listed, again.new) == (8, [])
    assert len(stored) == 44


@respx.mock
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429), "class quest list: HTTP 429"),
        (httpx.Response(200, json={"data": None}), "class quest list: unexpected response shape"),
    ],
)
def test_a_failed_list_is_reported(engine: Engine, response: httpx.Response, error: str) -> None:
    respx.get(f"{BASE_URL}/class-quests").mock(return_value=response)
    with Session(engine) as session, httpx.Client() as http:
        assert refresh_class_quests(session, http).errors == [error]
        assert stored_class_quests(session) == []


def store_list(engine: Engine) -> None:
    with Session(engine) as session, respx.mock, httpx.Client() as http:
        respx.get(f"{BASE_URL}/class-quests").mock(return_value=httpx.Response(200, json=LIST))
        refresh_class_quests(session, http)


def test_the_checklist_before_a_sync_or_a_refresh(client: TestClient, engine: Engine) -> None:  # noqa: F811
    empty = client.get("/api/class-quests").json()
    assert (empty["class_name"], empty["listed"], empty["rows"]) == (None, 0, [])

    store_list(engine)
    unsynced = client.get("/api/class-quests").json()
    assert (unsynced["listed"], unsynced["rows"]) == (44, [])  # no class to filter by


def test_the_checklist_and_done_marks(client: TestClient, engine: Engine) -> None:  # noqa: F811
    store_list(engine)
    client.post("/api/snapshots/manual", json={"kind": "profile", "payload": fixture("profile")})

    # The real profile: a level 18 Gnome Warrior, Alliance.
    checklist = client.get("/api/class-quests").json()
    assert (checklist["class_name"], checklist["level"], checklist["soon_levels"]) == (
        "Warrior",
        18,
        5,
    )
    rows = [(r["id"], r["status"], r["done"]) for r in checklist["rows"]]
    assert rows == [
        ("warrior-defensive-stance-dwarf", "missed", False),
        ("warrior-fire-hardened", "soon", False),
        ("warrior-berserker-stance", "later", False),
    ]

    done = client.put("/api/class-quests/warrior-defensive-stance-dwarf", json={"done": True})
    assert done.status_code == 200
    assert done.json()["rows"][0]["status"] == "done"
    undone = client.put("/api/class-quests/warrior-defensive-stance-dwarf", json={"done": False})
    assert undone.json()["rows"][0]["status"] == "missed"
    twice = client.put("/api/class-quests/warrior-fire-hardened", json={"done": False})
    assert twice.status_code == 200  # not done already: nothing to undo, no error

    missing = client.put("/api/class-quests/no-such-quest", json={"done": True})
    assert missing.status_code == 404
    bad = client.put("/api/class-quests/Not%20An%20Id", json={"done": True})
    assert bad.status_code == 422
