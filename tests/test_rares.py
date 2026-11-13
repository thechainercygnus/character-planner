"""Rares as an item pool source (#6, ADR 0029)."""

import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.companion import BASE_URL
from character_planner.db import CompanionRare
from character_planner.dungeons import Loot, parse_dungeon
from character_planner.pool import build_pool, in_window, level_window, pool_view, refresh_pool
from character_planner.rares import Rare, parse_levels, parse_rare, refresh_rares, stored_rares
from character_planner.recommend import Candidate, dungeon_values
from character_planner.targets import source_text

from .conftest import FIXTURES
from .test_dungeons import DEADMINES


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# Two real GET /rares responses, a minute apart (2026-11-13): the full list, and another
# client's cached `?zone=The Barrens` result served for the unfiltered path (ADR 0004).
FULL = fixture("companion_rares.json")
BARRENS = fixture("companion_rares_barrens.json")


def rare(rare_id: str) -> Rare:
    parsed = parse_rare(next(r for r in FULL["data"] if r["id"] == rare_id))
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ("10" + chr(0x2013) + "25", (10, 25)),  # as Forever Companion sends it: an en dash
        ("24-25", (24, 25)),  # as its spec writes it
        ("60", (60, 60)),
        ("?", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_levels(levels: Any, expected: tuple[int | None, int | None]) -> None:
    assert parse_levels(levels) == expected


def test_parse_a_real_rare() -> None:
    humar = rare("humar")
    assert (humar.name, humar.zone, humar.faction) == (
        "Humar the Pridelord",
        "The Barrens",
        "both",
    )
    assert (humar.min_level, humar.max_level, humar.spawns, humar.elite) == (10, 25, 1, False)
    [loot] = humar.loot
    assert (loot.item_id, loot.name, loot.slot, loot.quality) == (
        285331,
        "Mark of the Pack Leader",
        "neck",
        "UNCOMMON",
    )
    assert rare("swiftmane").spawns == 3


def test_every_real_rare_parses() -> None:
    parsed = [parse_rare(row) for row in FULL["data"]]
    assert len(parsed) == 28 and all(r is not None for r in parsed)
    assert parse_rare({"name": "No id"}) is None


@respx.mock
def test_a_filtered_list_never_shrinks_the_stored_rares(engine: Engine) -> None:
    route = respx.get(f"{BASE_URL}/rares")
    with Session(engine) as session, httpx.Client() as http:
        route.mock(return_value=httpx.Response(200, json=BARRENS))
        first = refresh_rares(session, http)
        route.mock(return_value=httpx.Response(200, json=FULL))
        full = refresh_rares(session, http)
        route.mock(return_value=httpx.Response(200, json=BARRENS))
        again = refresh_rares(session, http)
        stored = stored_rares(session)

    assert (first.listed, len(first.new)) == (3, 3)
    assert (full.listed, len(full.new)) == (28, 25)
    assert (again.listed, again.new) == (3, [])
    assert len(stored) == 28


@respx.mock
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503), "rare list: HTTP 503"),
        (
            httpx.Response(200, json={"data": {"not": "a list"}}),
            "rare list: unexpected response shape",
        ),
    ],
)
def test_a_failed_rare_list_keeps_what_is_stored(
    engine: Engine, response: httpx.Response, error: str
) -> None:
    with Session(engine) as session, httpx.Client() as http:
        session.add(CompanionRare(rare_id="humar", payload=FULL["data"][21]))
        session.commit()
        respx.get(f"{BASE_URL}/rares").mock(return_value=response)
        outcome = refresh_rares(session, http)
        assert outcome.errors == [error]
        assert [r.rare_id for r in session.exec(select(CompanionRare)).all()] == ["humar"]


def test_rare_drops_join_the_pool_as_rare_sources() -> None:
    pool = build_pool([], rares=[rare("humar"), rare("taskmaster-whipfang")])
    neck = pool[285331]
    assert (neck.name, neck.slot, neck.quality) == ("Mark of the Pack Leader", "neck", "UNCOMMON")
    [source] = neck.sources
    assert (source.kind, source.rare, source.zone, source.spawns) == (
        "rare",
        "Humar the Pridelord",
        "The Barrens",
        1,
    )
    assert (source.dungeon_id, source.place) == (None, "Humar the Pridelord")
    # No required level yet: the rare's lowest level is when it can be had.
    assert neck.effective_level == 10
    assert pool[284386].effective_level == 15  # Whipfang's Skinsearer, 15-25
    assert source_text(source) == "Rare: Humar the Pridelord, The Barrens"


def test_rares_respect_faction() -> None:
    horde_only = Rare(
        id="r", name="Raider", faction="horde", loot=[Loot(item_id=1, name="Horde Ring")]
    )
    assert 1 not in build_pool([], "alliance", rares=[horde_only])
    assert 1 in build_pool([], "horde", rares=[horde_only])
    assert 1 in build_pool([], None, rares=[horde_only])


def test_the_rares_level_range_sets_its_window() -> None:
    pool = build_pool([], rares=[rare("nightveiled-rotheap")])  # 20-30
    ring = pool[282283]
    assert in_window(ring, level_window(18))  # 15-28
    assert not in_window(ring, level_window(40))


def test_rares_are_not_dungeons_worth_running() -> None:
    deadmines = parse_dungeon(DEADMINES)
    assert deadmines is not None
    pool = build_pool([deadmines], rares=[rare("humar")])
    cape, neck = pool[5193], pool[285331]
    values = dungeon_values(
        {
            "BACK": [Candidate(item=cape, score_gain=3, usable_now=True)],
            "NECK": [Candidate(item=neck, score_gain=5, usable_now=True)],
        }
    )
    assert [v.dungeon_id for v in values] == ["the-deadmines"]
    assert [u.item.item_id for u in values[0].upgrades] == [5193]


@respx.mock
def test_a_pool_refresh_fetches_rares_and_their_item_details(engine: Engine) -> None:
    listing = {"data": [{"id": "the-deadmines", "status": "launch"}]}
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(200, json=listing))
    respx.get(f"{BASE_URL}/dungeons/the-deadmines").mock(
        return_value=httpx.Response(200, json=DEADMINES)
    )
    respx.get(f"{BASE_URL}/rares").mock(return_value=httpx.Response(200, json=FULL))
    items = respx.get(url__startswith=f"{BASE_URL}/items/").mock(return_value=httpx.Response(404))
    with Session(engine) as session, httpx.Client() as http:
        result = refresh_pool(session, level=18, faction="alliance", http=http, pause=0)
        view = pool_view(session, 18, "alliance")

    # Level 18's window is 15-28: every rare with drops overlaps it, beside The Deadmines.
    rare_drops = {285331, 285330, 285329, 284386, 282283}
    shown = {i.item_id for i in view.items}
    fetched = {int(str(c.request.url).rsplit("/", 1)[1]) for c in items.calls}
    assert result.rares_listed == 28
    assert result.errors == []
    assert rare_drops <= shown and rare_drops <= fetched
    assert shown - rare_drops == {5193, 2041, 2042}  # The Deadmines, alliance
