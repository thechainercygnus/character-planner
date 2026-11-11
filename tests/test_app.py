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
from .test_dungeons import mock_companion_dungeons
from .test_items import COMPANION, companion_responder, mock_battlenet

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
    assert off_hand["target_info"]["sources"] == ["blizzard"]  # Companion 404s for it here
    assert off_hand["target_info"]["item_level"] == 17
    assert off_hand["verdict"] == "downgrade"
    assert off_hand["item_level_delta"] == -4
    assert off_hand["equipped"]["icon_url"].endswith(".jpg")
    # Kindlegem Girdle isn't in Blizzard's search; Forever Companion has it by id.
    waist = next(row for row in gear["rows"] if row["slot"] == "WAIST")
    assert waist["target_info"]["sources"] == ["companion"]
    assert waist["target_info"]["item_level"] == 18
    assert waist["verdict"] == "upgrade"  # equipped belt is ilvl 14
    assert waist["armor_delta"] == 27  # 100 vs 73
    assert waist["stat_deltas"] == {"Stamina": 7}
    # Default weights: (100 x 0.1 + 7 x 1.0) - 73 x 0.1 = 9.7
    assert (waist["score_delta"], waist["verdict_basis"]) == (9.7, "score")
    assert gear["rows"][0]["slot"] == "WAIST"  # biggest gain sorts first
    assert off_hand["verdict_basis"] == "item_level"  # no stats for it: falls back
    assert gear["attributions"][0]["name"] == "Forever Companion"

    points = client.get("/api/progress").json()["points"]
    assert [(p["level"], p["item_level"]) for p in points] == [(18, 14.6)]

    summary = client.get("/api/summary.md").text
    assert "- Level: 18" in summary
    assert "Kindlegem Girdle" in summary
    assert "downgrade (ilvl 21 -> 17)" in summary
    assert "upgrade (ilvl 14 -> 18, score +9.7); +27 armor, +7 Stamina [companion]" in summary
    assert "Forever Companion" in summary


@respx.mock
def test_items_refresh_endpoint(client: TestClient) -> None:
    mock_battlenet()
    result = client.post("/api/items/refresh").json()
    assert "Dwarven Defender" in result["found"]
    assert "Kindlegem Girdle" in result["missing"]


@respx.mock
def test_items_refresh_reports_battlenet_outage_without_failing(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(503))
    respx.get(url__startswith=COMPANION).mock(side_effect=companion_responder)
    response = client.post("/api/items/refresh")
    assert response.status_code == 200
    assert any(error.startswith("Blizzard") for error in response.json()["errors"])
    assert response.json()["companion_fetched"] >= 1  # the other source still ran


@respx.mock
def test_pool_refresh_lists_items_and_fills_target_ids(client: TestClient) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    mock_companion_dungeons()

    result = client.post("/api/pool/refresh").json()
    assert result["dungeons_fetched"] == 2
    assert result["pool_size"] >= 13  # 10 Hall of Thanes drops + 3 alliance Deadmines items
    assert result["errors"] == []

    pool = client.get("/api/pool").json()
    assert (pool["level"], pool["faction"], pool["window"]) == (18, "alliance", [15, 28])
    pool_ids = {item["item_id"] for item in pool["items"]}
    assert {271098, 271097, 5193, 2041} <= pool_ids

    # Golemguard Chest and Spiritwraith Drape have no item_id in the YAML: the pool fills
    # them in by name.
    targets = client.get("/api/targets").json()["brackets"][0]["targets"]
    ids = {t["item"]: t["item_id"] for t in targets}
    assert ids["Golemguard Chest"] == 271098
    assert ids["Spiritwraith Drape"] == 271097
    assert ids["Kindlegem Girdle"] == 270230  # from the YAML

    # Only Kindlegem Girdle has item details in this test, and it isn't in the pool, so
    # every usable pool item is unscored; the shape is still complete.
    recs = client.get("/api/recommendations").json()
    assert recs["level"] == 18
    assert len(recs["rows"]) == 17
    neck = next(row for row in recs["rows"] if row["slot"] == "NECK")
    assert neck["equipped"] is None
    off_hand = next(row for row in recs["rows"] if row["slot"] == "OFF_HAND")
    assert off_hand["equipped"]["name"] == "Burnished Shield"
    assert recs["considered"] == 0


def test_pool_is_empty_before_any_refresh(client: TestClient) -> None:
    assert client.get("/api/pool").json() == {
        "level": None,
        "faction": None,
        "window": None,
        "items": [],
    }


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


def test_weights_api_edit_and_reset(client: TestClient) -> None:
    initial = client.get("/api/weights").json()
    assert initial["customised"] is False
    assert initial["weights"]["Stamina"] == 1.0

    edited = client.put("/api/weights", json={"weights": {"Stamina": 2.0}}).json()
    assert edited["customised"] is True
    assert edited["weights"]["Stamina"] == 2.0
    assert edited["weights"]["Armor"] == initial["defaults"]["Armor"]  # unspecified: default

    reset = client.delete("/api/weights").json()
    assert reset["customised"] is False
    assert reset["weights"]["Stamina"] == 1.0


def test_weights_api_rejects_bad_values(client: TestClient) -> None:
    assert client.put("/api/weights", json={"weights": {"Stamina": 99}}).status_code == 422
    assert client.put("/api/weights", json={"weights": {"": 1}}).status_code == 422
