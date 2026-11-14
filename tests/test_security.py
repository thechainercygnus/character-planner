"""Claims the assurance case (docs/assurance-case.md, #84) makes about the API.

Each test here backs a line in that document; change both together.
"""

import json

import pytest
from fastapi.testclient import TestClient

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
