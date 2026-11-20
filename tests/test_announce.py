"""Announcing a new version in the sign-up channel at start (#254), Discord mocked."""

import json

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import announce, worker
from character_planner.config import Settings
from character_planner.db import InstanceSetting

API = announce.API
CHANNEL = "1300000000000000001"
POST = f"{API}/channels/{CHANNEL}/messages"


@pytest.fixture
def configured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "discord_bot_token": SecretStr("bot-" + "z" * 40),
            "discord_signup_channel_id": CHANNEL,
        }
    )


def recorded(engine: Engine) -> object:
    with Session(engine) as session:
        row = session.get(InstanceSetting, announce.KEY)
        return None if row is None else row.value


def run(configured: Settings, engine: Engine, version: str) -> announce.Outcome:
    with Session(engine) as session, httpx.Client() as http:
        return announce.announce(session, configured, http, version)


def test_full_releases_only() -> None:
    assert announce.release("0.9.0") == (0, 9, 0)
    assert announce.release("0.10.12") == (0, 10, 12)
    for other in ("0.9.0rc1", "0.9.0-rc.1", "0.9.0.dev3", "unknown", "(not installed)", ""):
        assert announce.release(other) is None


@respx.mock
def test_the_first_start_records_without_announcing(configured: Settings, engine: Engine) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(200, json={"id": "1"}))
    assert run(configured, engine, "0.8.1") == "recorded"
    assert not posted.called
    assert recorded(engine) == "0.8.1"


@respx.mock
def test_a_new_release_is_announced_once(configured: Settings, engine: Engine) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(200, json={"id": "1"}))
    run(configured, engine, "0.8.1")
    assert run(configured, engine, "0.9.0") == "posted"
    assert run(configured, engine, "0.9.0") == "unchanged"  # a restart on the same version
    assert posted.call_count == 1
    body = json.loads(posted.calls[0].request.content)
    assert body["allowed_mentions"] == {"parse": []}
    content = body["content"]
    assert "0.9.0" in content
    assert "<https://github.com/thechainercygnus/character-planner/releases/tag/v0.9.0>" in content
    assert "<http://localhost:8000/>" in content
    assert "embeds" not in body
    assert recorded(engine) == "0.9.0"


@respx.mock
def test_a_pre_release_is_neither_announced_nor_recorded(
    configured: Settings, engine: Engine
) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(200, json={"id": "1"}))
    run(configured, engine, "0.8.1")
    assert run(configured, engine, "0.9.0rc1") == "pre-release"
    assert recorded(engine) == "0.8.1"
    assert run(configured, engine, "0.9.0") == "posted"  # the full release still is
    assert posted.call_count == 1


@respx.mock
def test_a_pre_release_on_the_first_start_records_nothing(
    configured: Settings, engine: Engine
) -> None:
    assert run(configured, engine, "0.9.0rc1") == "pre-release"
    assert recorded(engine) is None


@respx.mock
def test_a_rollback_is_recorded_quietly(configured: Settings, engine: Engine) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(200, json={"id": "1"}))
    run(configured, engine, "0.9.0")
    assert run(configured, engine, "0.8.1") == "unchanged"
    assert recorded(engine) == "0.8.1"
    assert not posted.called


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_a_refusal_is_logged_and_not_retried(
    configured: Settings, engine: Engine, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(status, json={}))
    run(configured, engine, "0.8.1")
    assert run(configured, engine, "0.9.0") == "refused"
    assert "wasn't announced" in caplog.text
    assert run(configured, engine, "0.9.0") == "unchanged"
    assert posted.call_count == 1


@respx.mock
def test_an_unreachable_discord_is_tried_at_the_next_start(
    configured: Settings, engine: Engine
) -> None:
    posted = respx.post(POST).mock(side_effect=httpx.ConnectError("down"))
    run(configured, engine, "0.8.1")
    assert run(configured, engine, "0.9.0") == "unreachable"
    assert recorded(engine) == "0.8.1"
    posted.mock(return_value=httpx.Response(200, json={"id": "1"}))
    assert run(configured, engine, "0.9.0") == "posted"


def test_off_without_the_channel_or_with_the_switch(
    settings: Settings, configured: Settings, engine: Engine
) -> None:
    assert run(settings, engine, "0.9.0") == "off"
    switched_off = configured.model_copy(update={"discord_announce_versions": False})
    assert run(switched_off, engine, "0.9.0") == "off"
    assert recorded(engine) is None


@respx.mock
def test_the_worker_announces_at_start_and_never_fails_on_it(
    configured: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = respx.post(POST).mock(return_value=httpx.Response(200, json={"id": "1"}))
    monkeypatch.setattr(worker.backup, "app_version", lambda: "0.8.1")
    worker.announce_version(configured, engine)
    monkeypatch.setattr(worker.backup, "app_version", lambda: "0.9.0")
    worker.announce_version(configured, engine)
    assert posted.call_count == 1
    monkeypatch.setattr(worker.backup, "app_version", lambda: "0.10.0")
    posted.mock(side_effect=RuntimeError("boom"))
    worker.announce_version(configured, engine)  # logged, not raised
