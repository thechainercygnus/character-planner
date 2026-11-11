import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings

from .conftest import FIXTURES
from .test_items import mock_battlenet

BASE = "https://us.api.blizzard.com/profile/wow/character/brumboldt-doomlet"


def fixture(kind: str) -> object:
    return json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(settings: Settings, engine: Engine):
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


def log_in(client: TestClient) -> None:
    login = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86399})
    )
    callback = client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:5173/"


def mock_character_api() -> None:
    for kind, suffix in [
        ("profile", ""),
        ("equipment", "/equipment"),
        ("statistics", "/statistics"),
        ("professions", "/professions"),
        ("specializations", "/specializations"),
    ]:
        respx.get(f"{BASE}{suffix}").mock(return_value=httpx.Response(200, json=fixture(kind)))
    respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(404, text="Not Found"))


def test_healthz(client: TestClient) -> None:
    assert client.get("/api/healthz").json() == {"status": "ok"}


def test_login_redirects_to_battlenet(client: TestClient) -> None:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith(oauth.AUTHORIZE_URL)


def test_callback_rejects_unknown_state(client: TestClient) -> None:
    assert client.get("/auth/callback?code=c&state=forged").status_code == 400


def test_sync_requires_login(client: TestClient) -> None:
    assert client.post("/api/sync").status_code == 401


@respx.mock
def test_login_sync_and_read_end_to_end(client: TestClient) -> None:
    log_in(client)
    assert client.get("/api/status").json()["logged_in"] is True

    mock_character_api()
    mock_battlenet()  # item search + media, called by sync's catalog refresh
    statuses = client.post("/api/sync").json()
    assert statuses["profile"] == 200
    assert statuses["appearance"] == 404

    latest = client.get("/api/snapshots/latest").json()
    assert "appearance" not in latest  # failures are stored but never "latest"

    character = client.get("/api/character").json()
    assert character["level"] == 18
    assert character["specialization"]["name"] == "Protection"
    assert character["stats"]["defense"] == 91

    gear = client.get("/api/gear").json()
    assert gear["bracket_min_level"] == 15
    off_hand = next(row for row in gear["rows"] if row["slot"] == "OFF_HAND")
    assert off_hand["equipped"]["name"] == "Burnished Shield"
    assert off_hand["target"]["item"] == "Dwarven Defender"
    assert off_hand["reached"] is False
    # The level-15 shield target is item level 17; the equipped shield is 21.
    assert off_hand["target_info"]["source"] == "api"
    assert off_hand["target_info"]["item_level"] == 17
    assert off_hand["verdict"] == "downgrade"
    assert off_hand["item_level_delta"] == -4
    assert off_hand["equipped"]["icon_url"].endswith(".jpg")
    waist = next(row for row in gear["rows"] if row["slot"] == "WAIST")
    assert waist["target_info"] is None  # Kindlegem Girdle isn't in the search index
    assert waist["verdict"] == "unknown"

    summary = client.get("/api/summary.md").text
    assert "- Level: 18" in summary
    assert "Kindlegem Girdle" in summary
    assert "downgrade (ilvl 21 -> 17)" in summary


@respx.mock
def test_items_refresh_endpoint(client: TestClient) -> None:
    mock_battlenet()
    result = client.post("/api/items/refresh").json()
    assert "Dwarven Defender" in result["found"]
    assert "Kindlegem Girdle" in result["missing"]


@respx.mock
def test_items_refresh_reports_battlenet_outage(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(503))
    assert client.post("/api/items/refresh").status_code == 502


def test_reads_are_empty_before_any_sync(client: TestClient) -> None:
    assert client.get("/api/character").json()["level"] is None
    assert client.get("/api/gear").json()["rows"] == []


def test_manual_snapshot_fills_gaps(client: TestClient) -> None:
    response = client.post(
        "/api/snapshots/manual", json={"kind": "professions", "payload": {"Mining": 93}}
    )
    assert response.status_code == 201
    assert client.get("/api/snapshots/latest").json()["professions"]["source"] == "manual"


def test_serves_built_frontend_when_present(
    settings: Settings, engine: Engine, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>planner</title>", encoding="utf-8")
    app = create_app(settings.model_copy(update={"frontend_dist": dist}), engine)

    with TestClient(app) as client:
        assert "<title>planner</title>" in client.get("/").text
        assert client.get("/api/healthz").json() == {"status": "ok"}  # API still wins
