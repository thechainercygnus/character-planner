"""The signed-in account's characters, and tracking one of them (#15)."""

import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.account import parse_account
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings

from .conftest import FIXTURES, api_client, tracked
from .test_app import fixture
from .test_worker import store_token

ACCOUNT_URL = "https://us.api.blizzard.com/profile/user/wow"
ACCOUNT: Any = json.loads((FIXTURES / "forever_account.json").read_text(encoding="utf-8"))


def test_the_account_lists_its_characters_highest_level_first() -> None:
    listed = parse_account(ACCOUNT)
    assert [(c.name, c.surname, c.slug, c.region, c.level) for c in listed] == [
        ("Brumboldt", "Doomlet", "brumboldt-doomlet", "us", 18),
        ("Testy", "Mcfixture", "testy-mcfixture", "us", 6),
        ("Sample", "Altington", "sample-altington", "us", 1),
    ]
    first = listed[0]
    assert (first.blizzard_id, first.character_class, first.race, first.faction) == (
        14060175,
        "Warrior",
        "Gnome",
        "ALLIANCE",
    )


def test_odd_entries_are_skipped_or_filled_in() -> None:
    payload = {
        "wow_accounts": [
            {"characters": [{"id": 5}, {"name": "Nohref", "surname": "Atall", "level": "x"}]},
            "not an account",
        ]
    }
    (only,) = parse_account(payload)
    assert (only.slug, only.region, only.level, only.character_class) == (
        "nohref-atall",
        "",
        None,
        None,
    )
    assert parse_account(None) == []


def test_listing_needs_the_battle_net_sign_in(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        response = client.get("/api/account/characters")
    assert response.status_code == 401
    assert "Sign in with Battle.net" in response.json()["detail"]


@respx.mock
def test_the_list_marks_the_characters_already_tracked(settings: Settings, engine: Engine) -> None:
    store_token(engine, 3600)
    route = respx.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=ACCOUNT))
    with Session(engine) as session:
        tracked(session)  # Brumboldt
    with api_client(create_app(settings, engine)) as client:
        listed = client.get("/api/account/characters").json()["characters"]
    assert [(c["slug"], c["tracked"]) for c in listed] == [
        ("brumboldt-doomlet", True),
        ("testy-mcfixture", False),
        ("sample-altington", False),
    ]
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"  # the login's


@respx.mock
@pytest.mark.parametrize(("status", "answer"), [(401, 401), (503, 502)])
def test_battle_net_errors_are_reported(
    settings: Settings, engine: Engine, status: int, answer: int
) -> None:
    store_token(engine, 3600)
    respx.get(ACCOUNT_URL).mock(return_value=httpx.Response(status, json={}))
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/account/characters").status_code == answer


@respx.mock
def test_a_picked_character_syncs_with_its_own_class_defaults(
    settings: Settings, engine: Engine
) -> None:
    """Track an alt from the account, sync it, and it gets a Priest's defaults (#80)
    while Brumboldt keeps the Warrior's."""
    store_token(engine, 3600)
    respx.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=ACCOUNT))
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    priest: Any = fixture("profile")
    priest |= {
        "id": 90000001,
        "name": "Testy",
        "surname": "Mcfixture",
        "level": 6,
        "character_class": {"name": "Priest", "id": 5},
    }
    alt = "https://us.api.blizzard.com/profile/wow/character/testy-mcfixture"
    respx.get(alt).mock(return_value=httpx.Response(200, json=priest))
    respx.route().mock(return_value=httpx.Response(404, json={"error": "Not found"}))
    with Session(engine) as session:
        tracked(session)
    with api_client(create_app(settings, engine)) as client:
        pick = next(
            c
            for c in client.get("/api/account/characters").json()["characters"]
            if c["slug"] == "testy-mcfixture"
        )
        added = client.post(
            "/api/characters",
            json={"name": pick["name"], "surname": pick["surname"], "region": pick["region"]},
        ).json()
        assert added["slug"] == pick["slug"]
        as_alt = {"X-Character-Id": str(added["id"])}
        assert client.post("/api/sync", headers=as_alt).json()["profile"] == 200
        alt_view = client.get("/api/character", headers=as_alt).json()
        assert (alt_view["character_class"], alt_view["level"]) == ("Priest", 6)
        assert client.get("/api/weights", headers=as_alt).json()["preset"] == "priest-leveling"
        assert client.get("/api/weights").json()["preset"] == "leveling-tank"  # Brumboldt
        relisted = client.get("/api/account/characters").json()["characters"]
    assert {c["slug"] for c in relisted if c["tracked"]} == {"brumboldt-doomlet", "testy-mcfixture"}
