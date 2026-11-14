"""Discord DMs (#58, ADR 0044): linking, delivery and refusals. Discord is mocked."""

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import discord, notify
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import NotificationDestination, NotificationOutbox, utcnow
from character_planner.notify import Digest

from .conftest import api_client, tracked_character
from .test_notify import WEBHOOK, _digests, add, outbox
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in

API = discord.API
DISCORD_ID = "80351110224678912"
GUILD_ID = "613425648685547541"
# Made up at run time, so no token-shaped string sits in the source.
BOT_TOKEN = "bot-" + "y" * 40


@pytest.fixture
def dms(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "discord_bot_token": SecretStr(BOT_TOKEN),
            "discord_client_id": "1234567890",
            "discord_client_secret": SecretStr("client-secret"),
            "discord_guild_id": GUILD_ID,
            "discord_invite_url": "https://discord.gg/planner",
        }
    )


@pytest.fixture
def client(dms: Settings, engine: Engine) -> Iterator[TestClient]:
    with api_client(create_app(dms, engine)) as test_client:
        yield test_client


def mock_identify(user_id: str = DISCORD_ID, name: str = "Brum") -> respx.Route:
    respx.post(discord.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "discord-user-token"})
    )
    return respx.get(f"{API}/users/@me").mock(
        return_value=httpx.Response(
            200, json={"id": user_id, "username": "brum_42", "global_name": name}
        )
    )


def link_in_browser(client: TestClient) -> Any:
    """The link as a browser goes through it: to Discord and back with a code."""
    start = client.get("/auth/discord/login", follow_redirects=False)
    assert start.status_code == 307
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get(f"/auth/discord/callback?code=c&state={state}", follow_redirects=False)


def mock_dm(status: int = 200, body: object = None, channel: str = "555") -> respx.Route:
    respx.post(f"{API}/users/@me/channels").mock(
        return_value=httpx.Response(200, json={"id": channel, "type": 1})
    )
    return respx.post(f"{API}/channels/{channel}/messages").mock(
        return_value=httpx.Response(status, json=body if body is not None else {"id": "1"})
    )


def linked_destination(session: Session, user_id: int | None = None) -> NotificationDestination:
    return discord.link(session, user_id, discord.Account(id=DISCORD_ID, name="Brum"))


# --- settings -----------------------------------------------------------------------------


def test_dms_need_the_bot_and_its_oauth_client(settings: Settings, dms: Settings) -> None:
    assert not settings.discord_dms
    assert dms.discord_dms
    assert not dms.model_copy(update={"discord_client_secret": SecretStr("")}).discord_dms


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discord_invite_url", "javascript:alert(1)"),
        ("discord_invite_url", "http://discord.gg/x"),
        ("discord_guild_id", "123/../../users"),
    ],
)
def test_discord_settings_are_checked(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


# --- hidden without the settings ----------------------------------------------------------


def test_hidden_without_the_discord_settings(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as plain:
        view = plain.get("/api/discord").json()
        assert view["available"] is False and view["linked"] is None
        assert plain.get("/auth/discord/login", follow_redirects=False).status_code == 404
        assert plain.patch("/api/discord", json={"enabled": False}).status_code == 404
        assert plain.post("/api/discord/test").status_code == 404


# --- linking ------------------------------------------------------------------------------


@respx.mock
def test_linking_stores_only_the_id_and_name(client: TestClient, engine: Engine) -> None:
    me = mock_identify()
    start = client.get("/auth/discord/login", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["scope"] == ["identify"]
    assert query["client_id"] == ["1234567890"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/discord/callback"]

    state = query["state"][0]
    back = client.get(f"/auth/discord/callback?code=c&state={state}", follow_redirects=False)
    assert back.status_code == 303
    assert me.calls.last.request.headers["Authorization"] == "Bearer discord-user-token"

    view = client.get("/api/discord").json()
    assert view["available"] is True
    assert view["invite_url"] == "https://discord.gg/planner"
    assert view["linked"]["name"] == "Brum"
    assert view["linked"]["alerts"] == notify.USER_ALERTS
    with Session(engine) as session:
        (row,) = session.exec(select(NotificationDestination)).all()
        assert (row.kind, row.discord_user_id, row.url) == ("discord_dm", DISCORD_ID, "")


@respx.mock
def test_a_link_needs_its_own_state(client: TestClient) -> None:
    mock_identify()
    assert client.get("/auth/discord/callback?code=c&state=forged").status_code == 400
    assert client.get("/api/discord").json()["linked"] is None


@respx.mock
def test_declining_on_discord_links_nothing(client: TestClient) -> None:
    start = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    back = client.get(
        f"/auth/discord/callback?error=access_denied&state={state}", follow_redirects=False
    )
    assert back.status_code == 303
    assert client.get("/api/discord").json()["linked"] is None


@respx.mock
def test_discord_refusing_the_code_is_reported(client: TestClient) -> None:
    respx.post(discord.TOKEN_URL).mock(return_value=httpx.Response(400, json={}))
    assert link_in_browser(client).status_code == 502
    assert client.get("/api/discord").json()["linked"] is None


@respx.mock
def test_linking_again_replaces_the_account(client: TestClient, engine: Engine) -> None:
    mock_identify()
    link_in_browser(client)
    mock_identify(user_id="99999999999999999", name="Alt")
    link_in_browser(client)
    with Session(engine) as session:
        (row,) = session.exec(select(NotificationDestination)).all()
        assert (row.name, row.discord_user_id) == ("Alt", "99999999999999999")


@respx.mock
def test_unlinking_deletes_the_id_name_and_unsent_dms(client: TestClient, engine: Engine) -> None:
    with Session(engine) as session:
        destination = linked_destination(session)
        assert destination.id is not None
        session.add(
            NotificationOutbox(
                destination_id=destination.id, kind="level_up", dedupe_key="k", payload={}
            )
        )
        session.commit()
    assert client.delete("/api/discord").json()["linked"] is None
    with Session(engine) as session:
        assert session.exec(select(NotificationDestination)).all() == []
        assert outbox(session) == []


def test_choosing_alerts_and_pausing(client: TestClient, engine: Engine) -> None:
    with Session(engine) as session:
        linked_destination(session)
    view = client.patch("/api/discord", json={"alerts": ["level_up"], "enabled": False}).json()
    assert view["linked"]["alerts"] == ["level_up"]
    assert view["linked"]["enabled"] is False
    # DMs carry the user's own alerts, never the operator's.
    assert client.patch("/api/discord", json={"alerts": ["job_failed"]}).status_code == 422
    assert client.delete("/api/discord").status_code == 200
    assert client.patch("/api/discord", json={"enabled": True}).status_code == 404


def test_the_admins_alert_settings_never_show_or_change_a_users_dms(
    client: TestClient, engine: Engine
) -> None:
    client.post("/api/notifications/destinations", json={"name": "Hook", "url": WEBHOOK})
    with Session(engine) as session:
        dm = linked_destination(session)
    view = client.get("/api/notifications").json()
    assert [d["name"] for d in view["destinations"]] == ["Hook"]
    assert client.patch(f"/api/notifications/destinations/{dm.id}", json={}).status_code == 404
    assert client.delete(f"/api/notifications/destinations/{dm.id}").status_code == 404


# --- users on -----------------------------------------------------------------------------


@respx.mock
def test_each_user_links_their_own_account(dms: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(
        dms.model_copy(update={"planner_users": True, "planner_signups": True}), engine
    )
    with browser(app) as admin, browser(app) as guildmate, browser(app) as stranger:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        assert stranger.get("/auth/discord/login").status_code == 401

        mock_identify()
        start = guildmate.get("/auth/discord/login", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        # Another browser can't finish someone else's link.
        assert admin.get(f"/auth/discord/callback?code=c&state={state}").status_code == 400
        start = guildmate.get("/auth/discord/login", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        guildmate.get(f"/auth/discord/callback?code=c&state={state}", follow_redirects=False)

        assert guildmate.get("/api/discord").json()["linked"]["name"] == "Brum"
        assert admin.get("/api/discord").json()["linked"] is None
        admin.delete("/api/discord")  # unlinks only the admin's own: there's none
        assert guildmate.get("/api/discord").json()["linked"] is not None

        assert guildmate.delete("/api/account").json()["removed"]["notificationdestination"] == 1
    with Session(engine) as session:
        assert session.exec(select(NotificationDestination)).all() == []


# --- alerts and delivery ------------------------------------------------------------------


def test_dms_get_only_the_owners_characters(
    engine: Engine, dms: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _digests(monkeypatch, Digest(level=19), Digest(level=20))
    with Session(engine) as session:
        mine = linked_destination(session)  # users off: the one user's
        theirs = discord.link(session, 42, discord.Account(id="1" * 17, name="Else"))
        assert notify.after_sync(session, dms, tracked_character(session)) == 0
        assert notify.after_sync(session, dms, tracked_character(session)) == 1
        assert [o.destination_id for o in outbox(session)] == [mine.id]
        assert theirs.id not in {o.destination_id for o in outbox(session)}


def test_system_alerts_never_go_to_dms(engine: Engine, dms: Settings) -> None:
    with Session(engine) as session:
        linked_destination(session)
        notify.job_failed(session, dms, "sync", "boom")
        assert outbox(session) == []


def test_a_day_holds_a_few_dms_at_most(
    engine: Engine, dms: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _digests(monkeypatch, Digest(level=19), Digest(level=20))
    with Session(engine) as session:
        destination = linked_destination(session)
        assert destination.id is not None
        for n in range(notify.DM_DAILY_CAP):
            session.add(
                NotificationOutbox(
                    destination_id=destination.id, kind="level_up", dedupe_key=f"{n}", payload={}
                )
            )
        session.commit()
        notify.after_sync(session, dms, tracked_character(session))
        assert notify.after_sync(session, dms, tracked_character(session)) == 0


def queue_one(session: Session) -> NotificationDestination:
    destination = linked_destination(session)
    assert destination.id is not None
    message = notify.build_message("Level-up", "Reached level 20.", notify.COLOR["user"])
    session.add(
        NotificationOutbox(
            destination_id=destination.id, kind="level_up", dedupe_key="k", payload=message
        )
    )
    session.commit()
    return destination


@respx.mock
def test_a_dm_is_sent_by_the_bot(engine: Engine, dms: Settings) -> None:
    sent = mock_dm()
    with Session(engine) as session, httpx.Client() as http:
        queue_one(session)
        assert notify.deliver_due(session, http, settings=dms) == 1
        (item,) = outbox(session)
        assert item.sent_at is not None
    opened = respx.calls[0].request
    assert json.loads(opened.content) == {"recipient_id": DISCORD_ID}
    assert opened.headers["Authorization"] == f"Bot {BOT_TOKEN}"
    assert opened.headers["User-Agent"].startswith("DiscordBot (")
    body = json.loads(sent.calls.last.request.content)
    assert "username" not in body  # a webhook's field
    assert body["allowed_mentions"] == {"parse": []}
    assert body["embeds"][0]["title"] == "Level-up"


@respx.mock
def test_without_the_bot_dms_wait(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session, httpx.Client() as http:
        queue_one(session)
        assert notify.deliver_due(session, http, settings=settings) == 0
        (item,) = outbox(session)
        assert item.sent_at is None and not item.failed
    assert not respx.calls


@respx.mock
@pytest.mark.parametrize(
    "body",
    [{"code": 50007, "message": "Cannot send messages to this user"}, {"code": 50001}],
)
def test_a_refused_dm_pauses_the_destination_and_is_not_retried(
    engine: Engine, dms: Settings, body: dict[str, object]
) -> None:
    mock_dm(status=403, body=body)
    with Session(engine) as session, httpx.Client() as http:
        destination = queue_one(session)
        assert notify.deliver_due(session, http, settings=dms) == 0
        session.refresh(destination)
        assert destination.enabled is False
        assert destination.last_error == notify.DM_REFUSED
        (item,) = outbox(session)
        assert item.failed
        calls = len(respx.calls)
        later = utcnow() + timedelta(days=1)
        assert notify.deliver_due(session, http, now=later, settings=dms) == 0
        assert len(respx.calls) == calls  # not retried


@respx.mock
def test_a_rate_limited_dm_waits_as_discord_says(engine: Engine, dms: Settings) -> None:
    mock_dm(status=429, body={"message": "You are being rate limited.", "retry_after": 30.5})
    with Session(engine) as session, httpx.Client() as http:
        queue_one(session)
        notify.deliver_due(session, http, settings=dms)
        (item,) = outbox(session)
        assert not item.failed and item.sent_at is None
        assert item.next_attempt_at > utcnow() + timedelta(seconds=29)


@respx.mock
def test_a_refused_bot_token_alerts_the_operator(engine: Engine, dms: Settings) -> None:
    respx.post(f"{API}/users/@me/channels").mock(return_value=httpx.Response(401, json={}))
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    with Session(engine) as session, httpx.Client() as http:
        add(session, audience="system")
        destination = queue_one(session)
        notify.deliver_due(session, http, settings=dms)
        session.refresh(destination)
        assert destination.enabled  # the user did nothing wrong
        dm, alert = sorted(outbox(session), key=lambda o: o.kind != "level_up")
        assert not dm.failed and dm.attempts == 0
        assert dm.next_attempt_at > utcnow() + timedelta(minutes=30)
        assert alert.kind == "job_failed"
        assert "DISCORD_BOT_TOKEN" in alert.payload["embeds"][0]["description"]
        assert BOT_TOKEN not in json.dumps(alert.payload)


# --- the test DM --------------------------------------------------------------------------


@respx.mock
def test_a_test_dm_that_gets_through_resumes_dms(client: TestClient, engine: Engine) -> None:
    respx.get(f"{API}/guilds/{GUILD_ID}/members/{DISCORD_ID}").mock(
        return_value=httpx.Response(200, json={"user": {"id": DISCORD_ID}})
    )
    mock_dm()
    with Session(engine) as session:
        destination = linked_destination(session)
        destination.enabled, destination.last_error = False, notify.DM_REFUSED
        session.add(destination)
        session.commit()
    view = client.post("/api/discord/test").json()
    assert view["in_server"] is True
    assert view["linked"]["enabled"] is True
    assert view["linked"]["last_error"] is None


@respx.mock
def test_a_test_dm_says_when_they_arent_in_the_server(client: TestClient, engine: Engine) -> None:
    respx.get(f"{API}/guilds/{GUILD_ID}/members/{DISCORD_ID}").mock(
        return_value=httpx.Response(404, json={"code": 10007, "message": "Unknown Member"})
    )
    mock_dm(status=403, body={"code": 50007})
    with Session(engine) as session:
        linked_destination(session)
    view = client.post("/api/discord/test").json()
    assert view["in_server"] is False
    assert view["linked"]["last_error"] == notify.DM_REFUSED
    assert view["invite_url"] == "https://discord.gg/planner"


@respx.mock
def test_membership_is_unknown_without_a_server_or_an_answer(dms: Settings) -> None:
    with httpx.Client() as http:
        no_server = dms.model_copy(update={"discord_guild_id": ""})
        assert discord.in_server(no_server, http, DISCORD_ID) is None
        respx.get(f"{API}/guilds/{GUILD_ID}/members/{DISCORD_ID}").mock(
            return_value=httpx.Response(403, json={"code": 50001})
        )
        assert discord.in_server(dms, http, DISCORD_ID) is None
