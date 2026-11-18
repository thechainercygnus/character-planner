"""Naming the items in an import (#185): the file has ids only (ADR 0047), so the view
names them from Forever Companion's items, then Blizzard's, and looks up the names and
icons it lacks in Blizzard's item data and media after the upload, caching both."""

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
from character_planner.db import BlizzardItem, CompanionItem, ItemIcon, utcnow

from .conftest import FIXTURES, api_client, tracked
from .test_gamedata import schema_example
from .test_items import ITEM, MEDIA, mock_battlenet

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


def requests_to(prefix: str) -> list[str]:
    """The Blizzard pages under `prefix` asked for, without their query."""
    urls = [str(c.request.url.copy_with(query=None)) for c in respx.calls]
    return sorted(url for url in urls if url.startswith(prefix))


# Every item's media answers with Lesser Healing Potion's (3655), as mock_battlenet does.
ICON = "https://render.worldofwarcraft.com/forever-us/icons/56/134949.jpg"


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
    # Then the lookup ran (in the background): Blizzard was asked about the other two,
    # their names and their icons. The girdle has both from Forever Companion.
    assert requests_to(ITEM) == [f"{ITEM}{GOGGLES}", f"{ITEM}{UNKNOWN}"]
    assert requests_to(MEDIA) == [f"{MEDIA}{GOGGLES}", f"{MEDIA}{UNKNOWN}"]
    items = client.get("/api/game-data").json()["items"]
    assert items[str(GOGGLES)] == {
        "name": "Flying Tiger Goggles",
        "quality": "RARE",  # the game's, from the file
        "icon_url": ICON,
        "wowhead": f"https://www.wowhead.com/forever/item={GOGGLES}",
    }
    # Blizzard has no name for it: unnamed, but it still links to Wowhead.
    assert items[str(UNKNOWN)]["name"] is None
    assert items[str(UNKNOWN)]["wowhead"] == f"https://www.wowhead.com/forever/item={UNKNOWN}"


def test_names_and_icons_are_cached_and_not_asked_again(client: TestClient, engine: Engine) -> None:
    client.post("/api/game-data", content=with_items(GOGGLES, UNKNOWN), headers=OCTET)
    asked = len(respx.calls)
    client.post("/api/game-data", content=with_items(GOGGLES, UNKNOWN), headers=OCTET)
    assert len(respx.calls) == asked  # the 404 counts as asked, too
    with Session(engine) as session:
        icon = session.get(ItemIcon, GOGGLES)
        assert icon is not None and icon.url == ICON


def test_a_cached_icon_is_used_without_asking(client: TestClient, engine: Engine) -> None:
    # Gear targets and equipped items fill the same cache (items.py).
    with Session(engine) as session:
        session.add(ItemIcon(item_id=GOGGLES, url=ICON))
        session.commit()
    response = client.post("/api/game-data", content=with_items(GOGGLES), headers=OCTET)
    assert response.json()["items"][str(GOGGLES)]["icon_url"] == ICON
    assert requests_to(MEDIA) == []


def test_stale_lookups_are_asked_again(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        character_id = tracked(session)
        character = session.get(gamedata.Character, character_id)
        assert character is not None
        gamedata.import_for(session, character, with_items(UNKNOWN))
        old = utcnow() - gamedata.REFRESH_AFTER - timedelta(days=1)
        session.add(BlizzardItem(item_id=UNKNOWN, found=False, fetched_at=old))
        session.add(ItemIcon(item_id=UNKNOWN, url=None, fetched_at=old))
        session.commit()
        wanted = gamedata.wanted_lookups(session, character_id)
        assert wanted == gamedata.Wanted(names=[UNKNOWN], icons=[UNKNOWN])


def test_a_failed_lookup_is_reported_and_stores_nothing(engine: Engine, settings: Settings) -> None:
    with respx.mock, Session(engine) as session:
        mock_battlenet()
        respx.get(url__startswith=ITEM).mock(return_value=httpx.Response(503))
        respx.get(url__startswith=MEDIA).mock(return_value=httpx.Response(503))
        wanted = gamedata.Wanted(names=[GOGGLES], icons=[GOGGLES])
        result = gamedata.fetch_item_details(session, settings, wanted)
        assert (result.names, result.icons) == (0, 0)
        assert result.errors == [f"item {GOGGLES}: HTTP 503", f"item media {GOGGLES}: HTTP 503"]
        assert session.get(BlizzardItem, GOGGLES) is None
        assert session.get(ItemIcon, GOGGLES) is None


def test_media_without_an_icon_is_cached_as_none(engine: Engine, settings: Settings) -> None:
    with respx.mock, Session(engine) as session:
        mock_battlenet()
        respx.get(url__startswith=MEDIA).mock(return_value=httpx.Response(404))
        result = gamedata.fetch_item_details(session, settings, gamedata.Wanted(icons=[UNKNOWN]))
        assert result.icons == 0 and result.errors == []
        icon = session.get(ItemIcon, UNKNOWN)
        assert icon is not None and icon.url is None


def test_nothing_wanted_means_no_lookup(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        result = gamedata.fetch_item_details(session, settings, gamedata.Wanted())
        assert result == gamedata.Lookup()


def test_the_quality_beyond_the_known_names_is_left_out() -> None:
    assert len(gamedata.QUALITY) == 8
    assert gamedata.QUALITY[3] == "RARE"
