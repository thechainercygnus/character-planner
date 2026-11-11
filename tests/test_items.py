import json
from typing import Any

import httpx
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import catalog_by_name, icons_by_id
from character_planner.items import exact_match, icon_url, refresh_catalog, search_queries

from .conftest import FIXTURES

SEARCH = "https://us.api.blizzard.com/data/wow/search/item"
MEDIA = "https://us.api.blizzard.com/data/wow/media/item/"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def search_responder(request: httpx.Request) -> httpx.Response:
    """Real search responses: Dwarven Defender is indexed, Flamefist Grips is not."""
    wanted = request.url.params["name.en_US"]
    if wanted == "Dwarven Defender":
        return httpx.Response(200, json=fixture("forever_item_search_dwarven_defender"))
    return httpx.Response(200, json=fixture("forever_item_search_flamefist_grips"))


def mock_battlenet() -> respx.Route:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.get(SEARCH).mock(side_effect=search_responder)
    return respx.get(url__startswith=MEDIA).mock(
        return_value=httpx.Response(200, json=fixture("forever_item_media_3655"))
    )


def test_exact_match_ignores_word_matches() -> None:
    body = fixture("forever_item_search_dwarven_defender")
    assert len(body["results"]) == 48  # word matches, e.g. "Dwarven Leather Pants"
    match = exact_match(body, "dwarven defender")
    assert match is not None
    assert match["id"] == 6187
    assert match["level"] == 17


def test_exact_match_returns_none_for_forever_new_items() -> None:
    assert exact_match(fixture("forever_item_search_flamefist_grips"), "Flamefist Grips") is None


def test_icon_url_from_media_response() -> None:
    url = icon_url(fixture("forever_item_media_3655"))
    assert url == "https://render.worldofwarcraft.com/forever-us/icons/56/134949.jpg"
    assert icon_url({"assets": []}) is None


@respx.mock
def test_refresh_caches_found_and_missing_items_and_icons(
    settings: Settings, engine: Engine
) -> None:
    media = mock_battlenet()
    with Session(engine) as session:
        result = refresh_catalog(
            session, settings, ["Dwarven Defender", "Flamefist Grips"], equipped_item_ids=[3655]
        )
        catalog = catalog_by_name(session)
        icons = icons_by_id(session)

    assert result.found == ["Dwarven Defender"]
    assert result.missing == ["Flamefist Grips"]
    assert result.errors == []
    assert catalog["dwarven defender"].item_id == 6187
    assert catalog["flamefist grips"].found is False
    assert set(icons) == {3655, 6187}
    assert media.call_count == 2


@respx.mock
def test_refresh_skips_cached_items_unless_forced(settings: Settings, engine: Engine) -> None:
    mock_battlenet()
    names = ["Dwarven Defender", "Flamefist Grips"]
    with Session(engine) as session:
        refresh_catalog(session, settings, names)
        again = refresh_catalog(session, settings, names)
        forced = refresh_catalog(session, settings, names, force=True)

    assert (again.found, again.missing, again.icons) == ([], [], 0)
    assert forced.found == ["Dwarven Defender"]
    assert forced.missing == ["Flamefist Grips"]


@respx.mock
def test_refresh_reports_search_errors_without_caching(settings: Settings, engine: Engine) -> None:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.get(SEARCH).mock(return_value=httpx.Response(500, text="oops"))
    with Session(engine) as session:
        result = refresh_catalog(session, settings, ["Dwarven Defender"])
        catalog = catalog_by_name(session)

    assert result.errors and "500" in result.errors[0]
    assert catalog == {}  # nothing cached, so the next sync tries again


@respx.mock
def test_search_follows_pages_until_exact_match(settings: Settings, engine: Engine) -> None:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    page_one = {"page": 1, "pageCount": 2, "results": []}
    page_two = fixture("forever_item_search_dwarven_defender") | {"page": 2, "pageCount": 2}
    search = respx.get(SEARCH).mock(
        side_effect=[httpx.Response(200, json=page_one), httpx.Response(200, json=page_two)]
    )
    respx.get(url__startswith=MEDIA).mock(return_value=httpx.Response(404))
    with Session(engine) as session:
        result = refresh_catalog(session, settings, ["Dwarven Defender"])

    assert result.found == ["Dwarven Defender"]
    assert [c.request.url.params["_page"] for c in search.calls] == ["1", "2"]


def test_search_queries_try_rare_words_after_the_full_name() -> None:
    assert search_queries("Cape of the Brotherhood") == [
        "Cape of the Brotherhood",
        "Brotherhood",
        "Cape",
    ]
    assert search_queries("Kresh's Back") == ["Kresh's Back", "Kresh's", "Back"]
    assert search_queries("Dull Sawblade") == ["Dull Sawblade", "Sawblade", "Dull"]


@respx.mock
def test_falls_back_to_single_words_when_the_full_name_is_buried(
    settings: Settings, engine: Engine
) -> None:
    """Common words push the exact match past the pages we read; a rare word finds it."""
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    cape = {"id": 5193, "name": {"en_US": "Cape of the Brotherhood"}, "level": 24}

    def responder(request: httpx.Request) -> httpx.Response:
        query = request.url.params["name.en_US"]
        if query == "Brotherhood":
            return httpx.Response(200, json={"pageCount": 1, "results": [{"data": cape}]})
        filler = [{"data": {"id": i, "name": {"en_US": f"Shirt of the {i}"}}} for i in range(100)]
        return httpx.Response(200, json={"pageCount": 40, "results": filler})

    search = respx.get(SEARCH).mock(side_effect=responder)
    respx.get(url__startswith=MEDIA).mock(return_value=httpx.Response(404))
    with Session(engine) as session:
        result = refresh_catalog(session, settings, ["Cape of the Brotherhood"])
        catalog = catalog_by_name(session)

    assert result.found == ["Cape of the Brotherhood"]
    assert catalog["cape of the brotherhood"].item_id == 5193
    queries = [c.request.url.params["name.en_US"] for c in search.calls]
    assert queries == ["Cape of the Brotherhood"] * 3 + ["Brotherhood"]
