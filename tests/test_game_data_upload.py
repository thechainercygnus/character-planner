"""Uploading the addon's game data (#184, ADR 0047): the file goes to the selected
character, must be that character's, replaces the previous import, and goes with the
character. The seeded character is Brumboldt Doomlet, US, as in addon/SCHEMA.md."""

from collections.abc import Iterator

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import GameDataImport
from character_planner.gamedata import LIMITS

from .conftest import FIXTURES, api_client, tracked
from .test_gamedata import schema_example
from .test_items import mock_battlenet

SAVED = FIXTURES / "savedvariables"
OCTET = {"Content-Type": "application/octet-stream"}


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    # An import looks up unnamed items in Blizzard's data afterwards (#185): mocked.
    with respx.mock, api_client(create_app(settings, engine)) as test_client:
        mock_battlenet()
        yield test_client


def upload(client: TestClient, body: bytes) -> object:
    return client.post("/api/game-data", content=body, headers=OCTET)


def imports(engine: Engine) -> list[GameDataImport]:
    with Session(engine) as session:
        return list(session.exec(select(GameDataImport)).all())


def test_nothing_is_imported_at_first(client: TestClient) -> None:
    assert client.get("/api/game-data").json() == {
        "imported": False,
        "uploaded_at": None,
        "captured_at": None,
        "addon_version": None,
        "captured": None,
        "data": None,
        "items": {},
    }


def test_an_upload_is_stored_and_shown_by_field_name(client: TestClient) -> None:
    response = upload(client, schema_example().encode())
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    view = client.get("/api/game-data").json()
    assert view["imported"] is True
    assert view["addon_version"] == "0.1.0"
    assert view["captured_at"].startswith("2026-11-14T")  # 1794700000, in UTC
    assert view["captured"]["bank"] is not None
    item = view["data"]["bags"]["items"][0]
    assert item == {"container": 0, "slot": 1, "item_id": 6948, "count": 1, "quality": 1}
    assert view["data"]["quests"]["log"][0]["quest_id"] == 1640
    assert "itemId" not in str(view)  # the API's names, not the file's


def test_a_new_upload_replaces_the_old(client: TestClient, engine: Engine) -> None:
    upload(client, schema_example().encode())
    upload(client, (SAVED / "example_crlf_bom.lua").read_bytes())
    (row,) = imports(engine)
    assert row.addon_version == "0.1.0"


def test_without_a_bank_section_the_bank_is_unknown(client: TestClient) -> None:
    minimal = (SAVED / "minimal_v1.lua").read_text(encoding="utf-8")
    view = upload(client, minimal.replace('"Lilalx"', '"Brumboldt"').encode()).json()  # type: ignore[attr-defined]
    assert view["captured"] == {"bags": None, "bank": None, "quests": None}


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (
            ('"Brumboldt"', '"Lilalx"'),
            "This file is Lilalx's, not Brumboldt Doomlet's: pick Lilalx",
        ),
        (('"Doomlet"', '"Horn"'), "This file is Brumboldt Horn's, not Brumboldt Doomlet's"),
        (('"US"', '"EU"'), "This file is from the EU region; Brumboldt Doomlet is US"),
    ],
)
def test_another_characters_file_is_refused(
    client: TestClient, engine: Engine, change: tuple[str, str], why: str
) -> None:
    body = schema_example().replace(*change).encode()
    response = upload(client, body)
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert response.json()["detail"] == why  # type: ignore[attr-defined]
    assert imports(engine) == []


def test_names_match_whatever_their_case(client: TestClient) -> None:
    body = schema_example().replace('"Brumboldt"', '"BRUMBOLDT"').replace('"US"', '"us"')
    assert upload(client, body.encode()).status_code == 200  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("body", "status", "why"),
    [
        (b"", 422, "No file"),
        (b'CharacterPlannerExportDB = os.execute("calc")', 422, "Couldn't read the file"),
        (b"BrotherBags = {}", 422, "No CharacterPlannerExportDB table"),
        (b"X = 1" + b" " * LIMITS.max_bytes, 413, "larger than 1024 KiB"),
    ],
)
def test_a_bad_upload_is_refused_and_stores_nothing(
    client: TestClient, engine: Engine, body: bytes, status: int, why: str
) -> None:
    response = upload(client, body)
    assert response.status_code == status  # type: ignore[attr-defined]
    assert why in response.json()["detail"]  # type: ignore[attr-defined]
    assert imports(engine) == []


def test_a_declared_size_over_the_limit_is_refused_before_reading(client: TestClient) -> None:
    headers = {**OCTET, "Content-Length": str(LIMITS.max_bytes + 1)}
    response = client.post("/api/game-data", content=b"x" * (LIMITS.max_bytes + 1), headers=headers)
    assert response.status_code == 413


def test_the_app_header_is_needed_to_upload(settings: Settings, engine: Engine) -> None:
    with TestClient(create_app(settings, engine)) as bare:
        assert bare.post("/api/game-data", content=b"x", headers=OCTET).status_code == 403


def test_deleting_it_and_deleting_the_character_both_remove_it(
    client: TestClient, engine: Engine
) -> None:
    upload(client, schema_example().encode())
    assert client.delete("/api/game-data").json()["imported"] is False
    assert imports(engine) == []
    upload(client, schema_example().encode())
    with Session(engine) as session:
        character_id = tracked(session)
    deleted = client.delete("/api/character", headers={"X-Character-Id": str(character_id)})
    assert deleted.json()["removed"]["gamedataimport"] == 1
    assert imports(engine) == []
