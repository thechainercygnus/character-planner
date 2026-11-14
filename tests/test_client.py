import time

import httpx
import respx

from character_planner.blizzard.client import CHARACTER_ENDPOINTS, BlizzardClient
from character_planner.blizzard.oauth import Token
from character_planner.config import Settings

BASE = "https://us.api.blizzard.com"


def token() -> Token:
    return Token("tok", time.time() + 3600, "wow.profile")


@respx.mock
def test_character_call_sends_namespace_and_bearer(settings: Settings) -> None:
    route = respx.get(f"{BASE}/profile/wow/character/brumboldt-doomlet").mock(
        return_value=httpx.Response(200, json={"level": 15})
    )
    with BlizzardClient(settings, token()) as client:
        result = client.character("profile", "brumboldt-doomlet")

    request = route.calls.last.request
    assert request.url.params["namespace"] == "profile-forever-us"
    assert request.headers["Authorization"] == "Bearer tok"
    assert result.ok and result.body == {"level": 15}


@respx.mock
def test_errors_and_non_json_bodies_are_returned_not_raised(settings: Settings) -> None:
    respx.get(f"{BASE}/profile/wow/character/brumboldt-doomlet/equipment").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    with BlizzardClient(settings, token()) as client:
        result = client.character("equipment", "brumboldt-doomlet")

    assert result.status == 404
    assert not result.ok
    assert result.body == "Not Found"


@respx.mock
def test_all_character_data_probes_every_endpoint(settings: Settings) -> None:
    respx.get(url__startswith=f"{BASE}/profile/wow/character/").mock(
        return_value=httpx.Response(200, json={})
    )
    with BlizzardClient(settings, token()) as client:
        results = client.all_character_data("brumboldt-doomlet")

    assert [r.kind for r in results] == list(CHARACTER_ENDPOINTS)


@respx.mock
def test_a_character_is_fetched_in_its_own_region(settings: Settings) -> None:
    """Characters carry their region (#14, ADR 0036): an EU one goes to the EU API."""
    route = respx.get("https://eu.api.blizzard.com/profile/wow/character/someone-else").mock(
        return_value=httpx.Response(200, json={})
    )
    with BlizzardClient(settings, token()) as client:
        client.character("profile", "someone-else", region="eu")
    assert route.calls.last.request.url.params["namespace"] == "profile-forever-eu"
