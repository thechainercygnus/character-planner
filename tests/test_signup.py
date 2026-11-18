"""The bot's pinned sign-up message (#192, ADR 0048), Discord mocked."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from character_planner import signup, worker
from character_planner.app import create_app
from character_planner.config import Settings

from .conftest import api_client

API = signup.API
CHANNEL = "1300000000000000001"
BOT = "1200000000000000001"
OURS = "1400000000000000001"
BOT_TOKEN = "bot-" + "z" * 40


@pytest.fixture
def configured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "discord_bot_token": SecretStr(BOT_TOKEN),
            "discord_signup_channel_id": CHANNEL,
            "planner_users": True,
            "planner_signups": True,
        }
    )


def pinned(*messages: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "items": [{"pinned_at": "2026-11-17T00:00:00+00:00", "message": m} for m in messages],
            "has_more": False,
        },
    )


def a_message(message_id: str, author: str, footer: str | None) -> dict[str, Any]:
    embeds = [{"footer": {"text": footer}}] if footer else []
    return {"id": message_id, "author": {"id": author}, "embeds": embeds}


def mock_discord(pins: httpx.Response) -> dict[str, respx.Route]:
    return {
        "me": respx.get(f"{API}/users/@me").mock(
            return_value=httpx.Response(200, json={"id": BOT})
        ),
        "pins": respx.get(f"{API}/channels/{CHANNEL}/messages/pins").mock(return_value=pins),
        "post": respx.post(f"{API}/channels/{CHANNEL}/messages").mock(
            return_value=httpx.Response(200, json={"id": OURS})
        ),
        "pin": respx.put(f"{API}/channels/{CHANNEL}/messages/pins/{OURS}").mock(
            return_value=httpx.Response(204)
        ),
        "edit": respx.patch(f"{API}/channels/{CHANNEL}/messages/{OURS}").mock(
            return_value=httpx.Response(200, json={"id": OURS})
        ),
        "delete": respx.delete(f"{API}/channels/{CHANNEL}/messages/{OURS}").mock(
            return_value=httpx.Response(204)
        ),
    }


def ensure(settings: Settings) -> signup.Outcome:
    with httpx.Client() as http:
        return signup.ensure(settings, http)


# --- the text ---------------------------------------------------------------------------------


def text(settings: Settings) -> str:
    return signup.message(settings)["embeds"][0]["description"]


def test_the_message_says_where_and_whether_sign_ups_are_open(configured: Settings) -> None:
    assert "http://localhost:8000/" in text(configured)
    assert "Sign-ups are open" in text(configured)
    closed = configured.model_copy(update={"planner_signups": False, "operator_contact": "Bryce"})
    assert "Sign-ups are closed" in text(closed) and "Ask Bryce to be let in" in text(closed)
    no_contact = closed.model_copy(update={"operator_contact": ""})
    assert "Ask whoever runs it" in text(no_contact)
    single = configured.model_copy(update={"planner_users": False})
    assert "nothing to sign up for" in text(single)


def test_the_message_mentions_dms_only_when_they_are_offered(configured: Settings) -> None:
    assert "Alerts as DMs" not in text(configured)
    dms = configured.model_copy(
        update={"discord_client_id": "1", "discord_client_secret": SecretStr("s")}
    )
    assert "Alerts as DMs" in text(dms)


def test_the_message_never_pings_and_carries_its_marker(configured: Settings) -> None:
    body = signup.message(configured)
    assert body["allowed_mentions"] == {"parse": []}
    assert body["embeds"][0]["footer"]["text"] == signup.MARKER


# --- keeping it pinned ------------------------------------------------------------------------


@respx.mock
def test_with_none_pinned_it_posts_and_pins_one(configured: Settings) -> None:
    routes = mock_discord(pinned())
    outcome = ensure(configured)
    assert outcome == signup.Outcome(ok=True, action="posted", message_id=OURS)
    sent = json.loads(routes["post"].calls.last.request.content)
    assert sent["embeds"][0]["footer"]["text"] == signup.MARKER
    assert routes["pin"].called and not routes["edit"].called
    assert routes["pins"].calls.last.request.headers["Authorization"] == f"Bot {BOT_TOKEN}"


@respx.mock
def test_its_own_pinned_message_is_edited_not_posted_again(configured: Settings) -> None:
    routes = mock_discord(
        pinned(a_message("1", "someone", None), a_message(OURS, BOT, signup.MARKER))
    )
    assert ensure(configured) == signup.Outcome(ok=True, action="updated", message_id=OURS)
    assert routes["edit"].called and not routes["post"].called and not routes["pin"].called


@respx.mock
def test_a_look_alike_by_someone_else_is_left_alone(configured: Settings) -> None:
    routes = mock_discord(pinned(a_message("9", "someone", signup.MARKER)))
    assert ensure(configured).action == "posted"
    assert not routes["edit"].called


@respx.mock
@pytest.mark.parametrize(
    ("status", "why"),
    [
        (401, "Discord refused DISCORD_BOT_TOKEN"),
        (403, "The bot isn't allowed to read the channel's pins: give it View Channel"),
        (404, "Discord doesn't know DISCORD_SIGNUP_CHANNEL_ID"),
        (429, "rate limiting the bot"),
        (500, "Discord answered 500 when trying to read the channel's pins"),
    ],
)
def test_a_refusal_is_reported_once_and_nothing_more_is_tried(
    configured: Settings, status: int, why: str
) -> None:
    routes = mock_discord(httpx.Response(status, json={"message": "no"}))
    outcome = ensure(configured)
    assert not outcome.ok and outcome.error is not None and why in outcome.error
    assert routes["pins"].call_count == 1  # not retried
    assert not routes["post"].called


@respx.mock
def test_a_refused_pin_takes_the_message_back(configured: Settings) -> None:
    routes = mock_discord(pinned())
    routes["pin"].mock(return_value=httpx.Response(403, json={"code": 50013}))
    outcome = ensure(configured)
    assert not outcome.ok and outcome.error is not None and "Pin Messages" in outcome.error
    assert routes["delete"].called  # or the next attempt would post a second one


@respx.mock
def test_discord_out_of_reach_is_reported(configured: Settings) -> None:
    respx.get(f"{API}/users/@me").mock(side_effect=httpx.ConnectError("down"))
    assert ensure(configured).error == "Couldn't reach Discord: try again"


def test_without_the_settings_nothing_is_attempted(settings: Settings) -> None:
    with respx.mock:  # any request would fail the test: none is mocked
        assert ensure(settings) == signup.Outcome(
            ok=False, action="none", error="DISCORD_SIGNUP_CHANNEL_ID isn't set"
        )


def test_the_channel_id_must_be_digits() -> None:
    with pytest.raises(ValidationError, match="DISCORD_SIGNUP_CHANNEL_ID must be a Discord id"):
        Settings(discord_signup_channel_id="123/../../users")  # type: ignore[call-arg]


# --- from the app, and from the worker --------------------------------------------------------


@pytest.fixture
def client(configured: Settings, engine: Engine) -> Iterator[TestClient]:
    with api_client(
        create_app(configured.model_copy(update={"planner_users": False}), engine)
    ) as c:
        yield c


@respx.mock
def test_the_admin_updates_it_from_the_app(client: TestClient) -> None:
    mock_discord(pinned())
    assert client.get("/api/discord").json()["signup_message"] is True
    assert client.post("/api/discord/signup-message").json()["action"] == "posted"


def test_the_route_is_absent_without_the_settings(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as plain:
        assert plain.get("/api/discord").json()["signup_message"] is False
        assert plain.post("/api/discord/signup-message").status_code == 404


@respx.mock
def test_the_worker_refreshes_it_at_start_and_never_fails_on_it(configured: Settings) -> None:
    routes = mock_discord(pinned(a_message(OURS, BOT, signup.MARKER)))
    worker.refresh_signup_message(configured)
    assert routes["edit"].called
    respx.get(f"{API}/users/@me").mock(side_effect=RuntimeError("boom"))
    worker.refresh_signup_message(configured)  # logged, not raised
