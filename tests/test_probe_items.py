import time

import httpx
import respx

from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.config import Settings
from character_planner.probe_items import KNOWN_ITEM_ID, SEARCH_NAMES, probe


@respx.mock
def test_client_credentials_requests_app_token(settings: Settings) -> None:
    route = respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    token = oauth.client_credentials(settings)

    assert b"grant_type=client_credentials" in route.calls.last.request.content
    assert token.access_token == "app"


@respx.mock
def test_get_can_override_namespace_and_add_params(settings: Settings) -> None:
    route = respx.get("https://us.api.blizzard.com/data/wow/search/item").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    token = oauth.Token("tok", time.time() + 3600, "")
    with BlizzardClient(settings, token) as client:
        client.get("search", "/data/wow/search/item", "static-forever-us", {"name.en_US": "X"})

    params = route.calls.last.request.url.params
    assert params["namespace"] == "static-forever-us"
    assert params["name.en_US"] == "X"
    assert params["locale"] == "en_US"


@respx.mock
def test_probe_tries_both_namespaces_and_every_search(settings: Settings) -> None:
    respx.get(url__startswith="https://us.api.blizzard.com/data/wow/").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    token = oauth.Token("tok", time.time() + 3600, "")
    with BlizzardClient(settings, token) as client:
        results = probe(client, "us")

    kinds = [r.kind for r in results]
    assert f"item-{KNOWN_ITEM_ID}-plain" in kinds
    assert f"item-{KNOWN_ITEM_ID}-versioned" in kinds
    assert len(results) == 2 * (2 + len(SEARCH_NAMES))
    assert all(r.status == 404 for r in results)
