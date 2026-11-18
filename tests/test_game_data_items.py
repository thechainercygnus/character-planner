"""Naming the items in an import (#185): the file has ids only (ADR 0047), so the view
names them from Forever Companion's items, then Blizzard's, and looks up the rest in
Blizzard's item data after the upload."""

import json
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import gamedata
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import BlizzardItem, CompanionItem, utcnow

from .conftest import FIXTURES, api_client, tracked
from .test_gamedata import schema_example
from .test_items import ITEM, mock_battlenet

OCTET = {"Content-Type": "application/octet-stream"}
GOGGLES = 4368  # Flying Tiger Goggles: a Blizzard item fixture (crafted gear's)
GIRDLE = 270230  # Kindlegem Girdle: a Forever Companion item fixture
UNKNOWN = 6948  # the schema example's item: neither catalog has it


def with_items(*item_ids: int) -> bytes:
    """The schema example with these items in the bags (quality 3, rare)."""
    entry = (
        '{{ ["container"] = 0, ["slot"] = {slot}, ["itemId"] = {id}, ["count"] = 1, '
        '["quality"] = 3 }},'
    )
    items = "\n".join(entry.format(slot=n, id=i) for n, i in enumerate(item_ids, start=1))
    example = schema_example()
    start = example.index('["items"] = {', example.index('["bags"]'))
    end = example.index('["bank"]')
    return (example[:start] + '["items"] = {\n' + items + "\n},\n},\n" + example[end:]).encode()


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with respx.mock, api_client(create_app(settings, engine)) as test_client:
        mock_battlenet()
        yield test_client


def store_girdle(engine: Engine) -> None:
    payload = json.loads((FIXTURES / "companion_item_270230.json").read_text(encoding="utf-8"))
    with Session(engine) as session:
        session.add(CompanionItem(item_id=GIRDLE, found=True, payload=payload))
        session.commit()


def item_requests() -> list[str]:
    """The Blizzard item pages asked for, without their query."""
    urls = [str(c.request.url.copy_with(query=None)) for c in respx.calls]
    return [url for url in urls if url.startswith(ITEM)]


def test_items_are_named_from_the_catalogs_and_unknown_ones_looked_up(
    client: TestClient, engine: Engine
) -> None:
    store_girdle(engine)
    body = with_items(GIRDLE, GOGGLES, UNKNOWN)
    response = client.post("/api/game-data", content=body, headers=OCTET)
    assert response.status_code == 200, response.text
    # The upload answers with what the catalogs knew then: Forever Companion's girdle.
    items = response.json()["items"]
    assert items[str(GIRDLE)]["name"] == "Kindlegem Girdle"
    assert items[str(GIRDLE)]["icon_url"]
    assert items[str(GOGGLES)]["name"] is None
    # Then the lookup ran (in the background): Blizzard was asked about the other two.
    assert sorted(item_requests()) == [f"{ITEM}{GOGGLES}", f"{ITEM}{UNKNOWN}"]
    items = client.get("/api/game-data").json()["items"]
    assert items[str(GOGGLES)] == {
        "name": "Flying Tiger Goggles",
        "quality": "RARE",  # the game's, from the file
        "icon_url": None,
        "wowhead": f"https://www.wowhead.com/forever/item={GOGGLES}",
    }
    # Blizzard doesn't know it either: unnamed, but it still links to Wowhead.
    assert items[str(UNKNOWN)]["name"] is None
    assert items[str(UNKNOWN)]["wowhead"] == f"https://www.wowhead.com/forever/item={UNKNOWN}"


def test_items_asked_about_recently_are_not_asked_again(client: TestClient) -> None:
    client.post("/api/game-data", content=with_items(GOGGLES, UNKNOWN), headers=OCTET)
    asked = len(item_requests())
    client.post("/api/game-data", content=with_items(GOGGLES, UNKNOWN), headers=OCTET)
    assert len(item_requests()) == asked  # the 404 counts as asked, too


def test_a_stale_404_is_asked_again(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        character_id = tracked(session)
        character = session.get(gamedata.Character, character_id)
        assert character is not None
        gamedata.import_for(session, character, with_items(UNKNOWN))
        old = utcnow() - gamedata.REFRESH_AFTER - timedelta(days=1)
        session.add(BlizzardItem(item_id=UNKNOWN, found=False, fetched_at=old))
        session.commit()
        assert gamedata.unnamed_item_ids(session, character_id) == [UNKNOWN]


def test_a_failed_lookup_is_reported_and_stores_nothing(engine: Engine, settings: Settings) -> None:
    with respx.mock, Session(engine) as session:
        mock_battlenet()
        respx.get(url__startswith=ITEM).mock(return_value=httpx.Response(503))
        result = gamedata.fetch_item_names(session, settings, [GOGGLES])
        assert result.fetched == 0
        assert result.errors == [f"item {GOGGLES}: HTTP 503"]
        assert session.get(BlizzardItem, GOGGLES) is None


def test_no_items_means_no_lookup(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        assert gamedata.fetch_item_names(session, settings, []).fetched == 0


def test_the_quality_beyond_the_known_names_is_left_out() -> None:
    assert len(gamedata.QUALITY) == 8
    assert gamedata.QUALITY[3] == "RARE"
