"""Claims the assurance case (docs/assurance-case.md, #84) makes about the API.

Each test here backs a line in that document; change both together.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from character_planner.app import create_app
from character_planner.config import Settings

from .conftest import api_client
from .test_app import client  # noqa: F401 (the client fixture)

CROSS_SITE = "https://evil.example"


def test_a_form_cant_send_a_json_body(client: TestClient) -> None:  # noqa: F811
    """A cross-site HTML form can only send form encodings or text/plain. JSON bodies are
    parsed only with a JSON content type, so a forged body never reaches the model."""
    body = json.dumps({"choice": "dismissed", "name": "Forged"})
    for content_type in ("text/plain", "application/x-www-form-urlencoded"):
        response = client.put(
            "/api/choices/5193", content=body, headers={"Content-Type": content_type}
        )
        assert response.status_code == 422
    assert client.get("/api/choices").json() == []


def test_no_cross_origin_access_is_granted(client: TestClient) -> None:  # noqa: F811
    """No CORS headers: another site's scripts can neither read responses nor make the
    preflighted requests (JSON bodies, PUT, DELETE)."""
    preflight = client.options(
        "/api/choices/5193",
        headers={"Origin": CROSS_SITE, "Access-Control-Request-Method": "PUT"},
    )
    assert "access-control-allow-origin" not in preflight.headers
    read = client.get("/api/status", headers={"Origin": CROSS_SITE})
    assert "access-control-allow-origin" not in read.headers


@pytest.mark.parametrize("state", ["", "made-up", "a" * 43])
def test_a_login_callback_needs_a_state_this_app_issued(
    client: TestClient,  # noqa: F811
    state: str,
) -> None:
    """OAuth state (CWE-352 on the login flow): a callback with a state the app didn't
    issue, or one already used, is refused before any code is exchanged."""
    response = client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 400


def test_input_is_validated_before_it_is_stored(client: TestClient) -> None:  # noqa: F811
    """Path and body values are checked against their models (types, ranges, patterns)."""
    assert (
        client.put("/api/choices/0", json={"choice": "dismissed", "name": "x"}).status_code == 422
    )
    assert client.put("/api/class-quests/../etc", json={"done": True}).status_code in (404, 422)
    assert client.get("/api/look-ahead", params={"levels": 99}).status_code == 422
    bad_hook = {"name": "x", "url": "https://example.com/hook", "alerts": []}
    assert client.post("/api/notifications/destinations", json=bad_hook).status_code == 422


@pytest.mark.parametrize("host", ["evil.example", "rebound.attacker.test:8000", "testserver.evil"])
def test_an_unknown_host_is_refused(client: TestClient, host: str) -> None:  # noqa: F811
    """DNS rebinding (#124): a request for a host name the instance doesn't answer to is
    refused before it reaches any route, reads included."""
    response = client.get("/api/status", headers={"Host": host})
    assert response.status_code == 400


def test_the_local_names_and_configured_hosts_are_answered(
    settings: Settings, engine: Engine
) -> None:
    lan = settings.model_copy(update={"planner_hosts": "Planner.Example.com, 192.168.1.20"})
    with api_client(create_app(lan, engine)) as local:
        for host in (
            "localhost",
            "127.0.0.1:8000",
            "[::1]:8000",
            "planner.example.com",
            "192.168.1.20",
        ):
            assert local.get("/api/healthz", headers={"Host": host}).status_code == 200
        assert local.get("/api/healthz", headers={"Host": "other.example"}).status_code == 400


def test_tailscale_names_are_answered_with_the_wildcard(settings: Settings, engine: Engine) -> None:
    tailnet = settings.model_copy(update={"planner_hosts": "*.ts.net"})
    with api_client(create_app(tailnet, engine)) as served:
        ok = served.get("/api/healthz", headers={"Host": "character-planner.tail1234.ts.net"})
        assert ok.status_code == 200
        assert served.get("/api/healthz", headers={"Host": "ts.net.evil"}).status_code == 400


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/sync"),
        ("POST", "/api/pool/refresh"),
        ("PUT", "/api/choices/5193"),
        ("DELETE", "/api/targets"),
    ],
)
def test_state_changing_requests_need_the_app_header(
    client: TestClient,  # noqa: F811
    method: str,
    path: str,
) -> None:
    """Cross-site forms (#124): even a body-less POST needs the header the web app
    sends, which a form can't set."""
    response = client.request(method, path, headers={"X-Requested-With": ""})
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_reads_dont_need_the_header(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/status", headers={"X-Requested-With": ""}).status_code == 200
