import json
import logging
import time
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs, notify, worker
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import (
    CompanionItem,
    NotificationDestination,
    NotificationOutbox,
    NotificationState,
    Snapshot,
    StoredToken,
    utcnow,
)
from character_planner.logs import RedactingFormatter, redact
from character_planner.notify import Digest

from .conftest import FIXTURES

# A made-up webhook, built at run time so no webhook URL sits in the source.
HOOK_ID = "123456789012345678"
HOOK_TOKEN = "fake-" + "x" * 60
WEBHOOK = f"https://discord.com/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}"
OTHER = f"https://discord.com/api/webhooks/987654321098765432/{HOOK_TOKEN}"


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


def add(session: Session, url: str = WEBHOOK, audience: str = "user", **kw: object) -> int:
    new = notify.NewDestination(name=f"{audience} hook", url=url, audience=audience, **kw)  # type: ignore[arg-type]
    destination = notify.add_destination(session, new)
    assert destination.id is not None
    return destination.id


def outbox(session: Session) -> list[NotificationOutbox]:
    return list(session.exec(select(NotificationOutbox)).all())


# --- webhook URLs -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        WEBHOOK,
        f"https://discordapp.com/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}",
        f"https://canary.discord.com/api/v10/webhooks/{HOOK_ID}/{HOOK_TOKEN}",
    ],
)
def test_discord_webhooks_are_accepted(url: str) -> None:
    assert notify.valid_webhook(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        f"http://discord.com/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}",  # not https
        f"https://discord.com.evil.example/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}",
        f"https://evil.example/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}",
        f"https://discord.com/api/webhooks/{HOOK_ID}/{HOOK_TOKEN}/../../users/@me",
        "https://discord.com/api/webhooks/abc/def",
        "",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    with pytest.raises(notify.NotifyError):
        notify.valid_webhook(url)


def test_urls_are_masked_and_redacted() -> None:
    assert notify.masked(WEBHOOK) == f"…/webhooks/{HOOK_ID}/••••"
    assert HOOK_TOKEN not in redact(f"posting to {WEBHOOK} failed")


# --- settings API -------------------------------------------------------------------------


def test_destinations_can_be_added_changed_and_removed(client: TestClient) -> None:
    empty = client.get("/api/notifications").json()
    assert empty["destinations"] == [] and empty["system_alerts_to_user"] is True
    assert {a["kind"] for a in empty["alerts"]} >= {"login_expired", "job_failed"}

    added = client.post("/api/notifications/destinations", json={"name": " Me ", "url": WEBHOOK})
    assert added.status_code == 201
    (dest,) = added.json()["destinations"]
    assert (dest["name"], dest["audience"], dest["enabled"]) == ("Me", "user", True)
    assert dest["url"] == f"…/webhooks/{HOOK_ID}/••••"
    assert dest["alerts"] == notify.USER_ALERTS + notify.SYSTEM_ALERTS
    assert HOOK_TOKEN not in added.text  # never sent back

    changed = client.patch(
        f"/api/notifications/destinations/{dest['id']}",
        json={"alerts": ["level_up"], "enabled": False, "name": "Phone"},
    ).json()["destinations"][0]
    assert (changed["alerts"], changed["enabled"], changed["name"]) == (
        ["level_up"],
        False,
        "Phone",
    )

    system = client.post(
        "/api/notifications/destinations",
        json={"name": "Ops", "url": OTHER, "audience": "system"},
    ).json()
    assert system["system_alerts_to_user"] is False
    assert system["destinations"][1]["alerts"] == notify.SYSTEM_ALERTS

    assert client.delete(f"/api/notifications/destinations/{dest['id']}").status_code == 200
    assert len(client.get("/api/notifications").json()["destinations"]) == 1
    assert client.delete(f"/api/notifications/destinations/{dest['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "url": "https://example.com/hook"},
        {"name": "", "url": WEBHOOK},
        {"name": "x", "url": WEBHOOK, "alerts": ["nonsense"]},
        {"name": "x", "url": WEBHOOK, "audience": "system", "alerts": ["level_up"]},
    ],
)
def test_bad_destinations_are_refused(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/api/notifications/destinations", json=body)
    assert response.status_code == 422
    assert client.get("/api/notifications").json()["destinations"] == []


@respx.mock
def test_a_test_send_reports_success_and_a_deleted_webhook(client: TestClient) -> None:
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    dest = client.post(
        "/api/notifications/destinations", json={"name": "Me", "url": WEBHOOK}
    ).json()["destinations"][0]

    ok = client.post(f"/api/notifications/destinations/{dest['id']}/test").json()
    assert ok["ok"] is True
    body = route.calls.last.request.read()
    assert b'"allowed_mentions":{"parse":[]}' in body.replace(b" ", b"")

    route.mock(return_value=httpx.Response(404, json={"message": "Unknown Webhook"}))
    gone = client.post(f"/api/notifications/destinations/{dest['id']}/test").json()
    assert (gone["ok"], gone["gone"]) == (False, True)
    assert client.get("/api/notifications").json()["destinations"][0]["last_error"] == "HTTP 404"


# --- routing --------------------------------------------------------------------------------


def test_system_alerts_go_to_user_destinations_until_a_system_one_exists(
    engine: Engine, settings: Settings
) -> None:
    with Session(engine) as session:
        user = add(session)
        notify.job_failed(session, settings, "pool", "boom")
        assert [o.destination_id for o in outbox(session)] == [user]

        system = add(session, url=OTHER, audience="system")
        notify.upstream_errors(session, settings, "pool", ["e"] * 12, rate_limited=False)
        assert [o.destination_id for o in outbox(session)] == [user, system]

        # User alerts never go to a system destination.
        notify.notify(session, "level_up", "level_up:20", notify._message("x", "y", 1))
        assert [o.destination_id for o in outbox(session)][-1] == user


def test_a_few_upstream_errors_are_not_worth_an_alert(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        add(session)
        notify.upstream_errors(session, settings, "pool", ["e"] * 3, rate_limited=False)
        assert outbox(session) == []
        notify.upstream_errors(session, settings, "pool", ["429"], rate_limited=True)
        assert len(outbox(session)) == 1


def test_disabled_or_unsubscribed_destinations_get_nothing(
    engine: Engine, settings: Settings
) -> None:
    with Session(engine) as session:
        add(session, alerts=["level_up"])
        off = add(session, url=OTHER)
        notify.update_destination(
            session,
            session.get(NotificationDestination, off),  # type: ignore[arg-type]
            notify.DestinationUpdate(enabled=False),
        )
        notify.job_failed(session, settings, "sync", "boom")
        assert outbox(session) == []


# --- login ------------------------------------------------------------------------------------


def test_login_alerts_are_sent_once_per_login(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        add(session)
        expires = time.time() + 3600 * 10
        session.add(StoredToken(id=1, access_token="t", expires_at=expires))
        session.commit()

        notify.check_login(session, settings, now=expires - 3 * 3600)  # 3h left: quiet
        assert outbox(session) == []
        notify.check_login(session, settings, now=expires - 3600)  # 1h left
        notify.check_login(session, settings, now=expires - 1800)  # again: no repeat
        (warning,) = outbox(session)
        assert warning.kind == "login_expiring"
        assert warning.payload["embeds"][0]["title"].startswith("Login expires in 1h")
        assert warning.payload["embeds"][0]["url"] == "http://localhost:8000/auth/login"

        notify.check_login(session, settings, now=expires + 5)
        notify.check_login(session, settings, now=expires + 600)
        assert [o.kind for o in outbox(session)] == ["login_expiring", "login_expired"]


# --- changes after a sync -----------------------------------------------------------------


def _digests(monkeypatch: pytest.MonkeyPatch, *digests: Digest) -> None:
    queue = list(digests)
    monkeypatch.setattr(
        notify,
        "character_digest",
        lambda _session, _settings: (queue.pop(0), ["**Cape** (Back, The Deadmines): +4.0"]),
    )


def test_changes_since_the_last_sync_become_one_message(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = Digest(level=19, targets={"BACK": "1"}, names={"1": "Drape"}, upgrades=[5])
    second = Digest(
        level=20,
        targets={"BACK": "2", "WAIST": "3"},
        reached=["WAIST:3"],
        names={"2": "Cape of the Brotherhood", "3": "Cobrahn's Grasp"},
        upgrades=[5, 6],
    )
    _digests(monkeypatch, first, second, second)
    with Session(engine) as session:
        add(session)
        levels_only = add(session, url=OTHER, alerts=["level_up"])

        assert notify.after_sync(session, settings) == 0  # the baseline
        assert session.get(NotificationState, "digest") is not None

        assert notify.after_sync(session, settings) == 2
        everything, level = sorted(outbox(session), key=lambda o: o.destination_id != 1)
        fields = {f["name"]: f["value"] for f in everything.payload["embeds"][0]["fields"]}
        assert fields == {
            "Level-up": "Reached **level 20**.",
            "Targets reached": "• Cobrahn's Grasp (Waist)",
            "Targets now in reach": "• Cape of the Brotherhood (Back)",
            "Upgrades worth having": "**Cape** (Back, The Deadmines): +4.0",
        }
        assert everything.payload["embeds"][0]["url"] == "http://localhost:8000/#plan"
        assert level.destination_id == levels_only
        assert [f["name"] for f in level.payload["embeds"][0]["fields"]] == ["Level-up"]

        assert notify.after_sync(session, settings) == 0  # nothing changed


def test_no_destinations_means_no_digest_work(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise AssertionError("digest built with nowhere to send")

    monkeypatch.setattr(notify, "character_digest", fail)
    with Session(engine) as session:
        assert notify.after_sync(session, settings) == 0


def test_the_digest_reads_the_real_plan(engine: Engine, settings: Settings) -> None:
    from character_planner.db import Snapshot

    from .test_views import payload

    with Session(engine) as session:
        for kind in ("profile", "equipment"):
            session.add(Snapshot(source="api", kind=kind, status=200, payload=payload(kind)))
        session.commit()
        digest, lines = notify.character_digest(session, settings)
    assert digest.level == 18
    assert "OFF_HAND" in digest.targets  # the YAML's current shield target
    assert digest.upgrades == [] and lines == []  # no item pool in this test


@respx.mock
def test_a_failing_alert_never_fails_a_sync(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from .test_app import log_in, mock_character_api
    from .test_items import mock_battlenet

    def boom(*_: object) -> int:
        raise RuntimeError("alerts broke")

    monkeypatch.setattr(notify, "after_sync", boom)
    log_in(client)
    mock_character_api()
    mock_battlenet()
    with caplog.at_level(logging.ERROR):
        assert client.post("/api/sync").status_code == 200
    assert "Notifications after the sync failed" in caplog.text


# --- delivery ---------------------------------------------------------------------------------


def _queue_one(session: Session, key: str = "k") -> NotificationOutbox:
    notify.notify(session, "level_up", key, notify._message("t", "d", 1))
    return outbox(session)[-1]


@respx.mock
def test_delivery_sends_retries_and_gives_up(engine: Engine) -> None:
    route = respx.post(WEBHOOK)
    with Session(engine) as session, httpx.Client() as http:
        add(session)
        item = _queue_one(session)

        route.mock(return_value=httpx.Response(500))
        assert notify.deliver_due(session, http) == 0
        session.refresh(item)
        assert (item.attempts, item.sent_at, item.failed) == (1, None, False)
        assert notify.deliver_due(session, http) == 0  # backing off: not due yet
        assert item.attempts == 1

        for _ in range(notify.MAX_ATTEMPTS):
            item.next_attempt_at = utcnow() - timedelta(seconds=1)
            session.add(item)
            session.commit()
            notify.deliver_due(session, http)
            session.refresh(item)
        assert (item.failed, item.attempts) == (True, notify.MAX_ATTEMPTS)

        item2 = _queue_one(session, "k2")
        route.mock(return_value=httpx.Response(204))
        assert notify.deliver_due(session, http) == 1
        session.refresh(item2)
        assert item2.sent_at is not None
        destination = session.get(NotificationDestination, item2.destination_id)
        assert destination is not None and destination.last_error is None


@respx.mock
def test_delivery_waits_when_discord_rate_limits(engine: Engine) -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(429, json={"retry_after": 30.0}))
    with Session(engine) as session, httpx.Client() as http:
        add(session)
        first = _queue_one(session, "a")
        second = _queue_one(session, "b")
        notify.deliver_due(session, http)
        session.refresh(first)
        session.refresh(second)
    assert first.attempts == 1 and first.next_attempt_at > utcnow() + timedelta(seconds=20)
    assert second.attempts == 0  # the batch stopped


@respx.mock
def test_a_deleted_webhook_marks_its_destination_failing(engine: Engine) -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(404))
    with Session(engine) as session, httpx.Client() as http:
        add(session)
        item = _queue_one(session)
        notify.deliver_due(session, http)
        session.refresh(item)
        destination = session.get(NotificationDestination, item.destination_id)
    assert item.failed and item.attempts == 1
    assert destination is not None and "deleted" in (destination.last_error or "")


@respx.mock
def test_webhook_urls_never_reach_the_log(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(WEBHOOK).mock(return_value=httpx.Response(404))
    with caplog.at_level(logging.DEBUG), Session(engine) as session, httpx.Client() as http:
        add(session)
        _queue_one(session)
        notify.deliver_due(session, http)
    # Our own lines never include the URL. httpx's request line does (at DEBUG only), so
    # check what the app's formatter writes, which is what reaches the console and files.
    ours = [r for r in caplog.records if r.name.startswith("character_planner")]
    assert ours and all(HOOK_TOKEN not in r.getMessage() for r in ours)
    formatter = RedactingFormatter("%(name)s %(message)s")
    written = "\n".join(formatter.format(r) for r in caplog.records)
    assert f"webhooks/{HOOK_ID}/[redacted]" in written
    assert HOOK_TOKEN not in written


# --- worker -----------------------------------------------------------------------------------


@respx.mock
def test_a_failing_scheduled_job_is_a_system_alert(engine: Engine, settings: Settings) -> None:
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))

    def broken(*_: object) -> str:
        raise RuntimeError("worker job exploded")

    schedule = worker.Schedule(jobs=[worker.Job("pool", timedelta(hours=1), broken)])
    with Session(engine) as session:
        add(session)
    outcomes = worker.run_due(engine, settings, schedule, utcnow())
    assert outcomes["pool"].startswith("failed: RuntimeError")
    with httpx.Client() as http:
        worker.tick_notifications(engine, settings, http)
    assert route.called
    body = route.calls.last.request.read().decode()
    assert "Scheduled pool failed" in body and "worker job exploded" in body


def test_jobs_send_sync_alerts_is_best_effort(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notify, "after_sync", lambda *_: 1 / 0)
    with Session(engine) as session:
        jobs.send_sync_alerts(session, settings)  # logs, never raises


def test_no_upgrade_alerts_without_a_level(engine: Engine, settings: Settings) -> None:
    """With no level the pool isn't windowed: don't suggest every item in the game."""
    from .test_dungeons import mock_companion_dungeons

    with respx.mock, TestClient(create_app(settings, engine)) as client:
        mock_companion_dungeons()
        respx.get(url__startswith="https://forevercompanion.io/api/v1/items/").mock(
            return_value=httpx.Response(404, json={})
        )
        client.post("/api/pool/refresh")
    with Session(engine) as session:
        # Give one pool item real stats, so it would be an upgrade over an empty slot.
        details = json.loads((FIXTURES / "companion_item_270230.json").read_text("utf-8"))
        session.merge(CompanionItem(item_id=5193, found=True, payload=details))
        session.commit()
        digest, lines = notify.character_digest(session, settings)
        assert digest.level is None and digest.upgrades == [] and lines == []

        # The same pool with a level does produce it, so the guard is what stopped it.
        session.add(Snapshot(source="api", kind="profile", status=200, payload={"level": 18}))
        session.commit()
        with_level, _ = notify.character_digest(session, settings)
    assert with_level.level == 18 and with_level.upgrades == [5193]
