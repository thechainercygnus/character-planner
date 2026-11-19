"""The level planning uses (#186, ADR 0052): the newest of the last sync and the game data,
labelled with its source. The synced profile fixture is level 18; the schema example's
file is level 24."""

from datetime import timedelta

import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.db import utcnow
from character_planner.levels import effective_level, planning_level

from .conftest import tracked
from .test_app import client, mock_character_api  # noqa: F401 (the client fixture)
from .test_gamedata import schema_example
from .test_items import mock_battlenet

OCTET = {"Content-Type": "application/octet-stream"}
EXAMPLE_AT = 1794700000  # the schema example's capturedAt: 2026-11-14, before any sync here


def game_file(captured_at: int) -> bytes:
    """The schema example (level 24), captured at this Unix time."""
    return schema_example().replace(f"= {EXAMPLE_AT},", f"= {captured_at},").encode()


def sync(client: TestClient) -> None:  # noqa: F811
    mock_character_api()
    mock_battlenet()
    assert client.post("/api/sync").json()["profile"] == 200


def character_id(engine: Engine) -> int:
    with Session(engine) as session:
        return tracked(session)


def test_no_sync_and_no_import_means_no_level(engine: Engine) -> None:
    with Session(engine) as session:
        assert effective_level(session, None) is None
        assert effective_level(session, tracked(session)) is None
        assert planning_level(session, tracked(session)) is None


@respx.mock
def test_the_last_sync_wins_over_an_older_file(client: TestClient, engine: Engine) -> None:  # noqa: F811
    sync(client)
    client.post("/api/game-data", content=game_file(EXAMPLE_AT), headers=OCTET)
    source = client.get("/api/character").json()["level_source"]
    assert (source["level"], source["source"]) == (18, "battle.net")
    assert client.get("/api/gear").json()["level"] == 18


@respx.mock
def test_a_file_newer_than_the_sync_wins_everywhere(client: TestClient, engine: Engine) -> None:  # noqa: F811
    sync(client)
    later = int((utcnow() + timedelta(minutes=5)).timestamp())
    upload = client.post("/api/game-data", content=game_file(later), headers=OCTET)
    assert upload.status_code == 200, upload.text

    character = client.get("/api/character").json()
    assert character["level"] == 18  # the Character tab is still the sync's snapshot
    assert (character["level_source"]["level"], character["level_source"]["source"]) == (
        24,
        "game",
    )
    assert character["level_source"]["at"].startswith(utcnow().date().isoformat()[:4])
    # Every planning view uses it: the gear plan, the upgrades, Look ahead.
    assert client.get("/api/gear").json()["level"] == 24
    assert client.get("/api/recommendations").json()["level"] == 24
    assert client.get("/api/look-ahead").json()["level"] == 24

    # Deleting the import puts Battle.net's back.
    client.delete("/api/game-data")
    assert client.get("/api/gear").json()["level"] == 18


@respx.mock
def test_a_newer_sync_takes_over_again(client: TestClient, engine: Engine) -> None:  # noqa: F811
    sync(client)
    later = int((utcnow() + timedelta(minutes=5)).timestamp())
    client.post("/api/game-data", content=game_file(later), headers=OCTET)
    with Session(engine) as session:
        found = effective_level(session, character_id(engine))
        assert found is not None and found.source == "game"
    # A file captured before the last sync can't outvote it.
    client.post("/api/game-data", content=game_file(EXAMPLE_AT), headers=OCTET)
    with Session(engine) as session:
        found = effective_level(session, character_id(engine))
        assert found is not None and (found.level, found.source) == (18, "battle.net")


def test_a_file_alone_gives_the_level(client: TestClient, engine: Engine) -> None:  # noqa: F811
    with respx.mock:
        mock_battlenet()  # the upload's item lookups
        client.post("/api/game-data", content=game_file(EXAMPLE_AT), headers=OCTET)
    with Session(engine) as session:
        found = effective_level(session, character_id(engine))
        assert found is not None and (found.level, found.source) == (24, "game")
