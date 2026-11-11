import json
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

BASE = "https://us.api.blizzard.com/profile/wow/character/brumboldt-doomlet"


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


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_login_redirects_to_battlenet(client: TestClient) -> None:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith(oauth.AUTHORIZE_URL)


def test_callback_rejects_unknown_state(client: TestClient) -> None:
    assert client.get("/auth/callback?code=c&state=forged").status_code == 400


def test_sync_requires_login(client: TestClient) -> None:
    assert client.post("/sync").status_code == 401


@respx.mock
def test_login_sync_and_summary_end_to_end(client: TestClient) -> None:
    log_in(client)
    assert client.get("/status").json()["logged_in"] is True

    profile = json.loads((FIXTURES / "synthetic_profile.json").read_text(encoding="utf-8"))
    equipment = json.loads((FIXTURES / "synthetic_equipment.json").read_text(encoding="utf-8"))
    respx.get(BASE).mock(return_value=httpx.Response(200, json=profile))
    respx.get(f"{BASE}/equipment").mock(return_value=httpx.Response(200, json=equipment))
    respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(404, text="Not Found"))

    statuses = client.post("/sync").json()
    assert statuses["profile"] == 200
    assert statuses["professions"] == 404

    latest = client.get("/snapshots/latest").json()
    assert set(latest) == {"profile", "equipment"}  # failures are stored but not "latest"

    summary = client.get("/summary.md").text
    assert "- Level: 15" in summary
    assert "Kindlegem Girdle" in summary


def test_manual_snapshot_fills_gaps(client: TestClient) -> None:
    response = client.post(
        "/snapshots/manual", json={"kind": "professions", "payload": {"Mining": 93}}
    )
    assert response.status_code == 201
    assert client.get("/snapshots/latest").json()["professions"]["source"] == "manual"
