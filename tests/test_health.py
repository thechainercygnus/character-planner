"""Instance health in the admin area (#241): database, queue, failures, budget and refreshes,
with and without Redis, and never a token, a secret or another user's data."""

import json
from datetime import timedelta
from typing import Any

import fakeredis
import pytest
import respx
from fastapi import FastAPI
from rq import Queue, SimpleWorker, Worker
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import health, leases, queue, upstream, worker
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import CompanionItem, InstanceSetting, utcnow

from .test_data_requests import open_app
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in

SECRET = "s3cr3t-client-value"


def boom() -> None:
    raise RuntimeError(f"Battle.net said no: access_token={SECRET}")


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(queue, "connect", lambda _url: fake)
    return fake


def health_app(settings: Settings, engine: Engine, **update: Any) -> FastAPI:
    return open_app(settings.model_copy(update={"planner_users": True, **update}), engine)


@respx.mock
def test_without_redis_the_admin_sees_the_database_and_the_refreshes(
    settings: Settings, engine: Engine
) -> None:
    mock_battle_net()
    with Session(engine) as session:
        session.add(CompanionItem(item_id=1, found=True, payload={}))
        session.commit()
    with browser(health_app(settings, engine)) as admin:
        sign_in(admin, ADMIN)
        body = admin.get("/api/admin/health").json()
    assert body["ready"] is True
    assert body["database"] == {"reachable": True, "migrated": True}
    assert body["queue"]["configured"] is False
    assert body["failures"] == []
    refreshes = {r["name"]: r["last"] for r in body["refreshes"]}
    assert refreshes["Item pool"] is not None
    assert refreshes["Enchants"] is None  # never refreshed
    assert set(refreshes) == {"Item pool", "Enchants", "Recipes", "Game items", "Talent trees"}


@respx.mock
def test_only_a_role_with_health_view_may_look(settings: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = health_app(settings, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        assert guildmate.get("/api/admin/health").status_code == 403
        assert admin.get("/api/admin/health").status_code == 200


@respx.mock
def test_with_redis_the_queue_its_worker_and_failed_jobs_show(
    settings: Settings, engine: Engine, redis: Any
) -> None:
    mock_battle_net()
    app = health_app(settings, engine, redis_url="redis://fake")
    jobs = Queue(queue.QUEUE, connection=redis)
    jobs.enqueue(boom, job_id="sync-42")
    jobs.enqueue(boom, job_id="refresh-pool")
    SimpleWorker([jobs], connection=redis).work(burst=True)
    jobs.enqueue(boom, job_id="sync-7")  # still waiting
    idle = Worker([jobs], connection=redis)
    idle.register_birth()
    idle.heartbeat()
    with browser(app) as admin:
        sign_in(admin, ADMIN)
        response = admin.get("/api/admin/health")
    body = response.json()
    assert body["queue"]["configured"] and body["queue"]["reachable"]
    assert body["queue"]["queued"] == 1
    assert body["queue"]["failed"] == 2
    assert body["queue"]["workers"] >= 1
    assert body["queue"]["last_heartbeat"] is not None
    assert sorted(f["job"] for f in body["failures"]) == ["refresh pool", "sync"]
    # A character's id and a token never appear.
    assert SECRET not in response.text
    assert "sync-42" not in response.text
    assert "[redacted]" in response.text


@respx.mock
def test_an_unreachable_queue_shows_as_such(settings: Settings, engine: Engine, redis: Any) -> None:
    mock_battle_net()
    app = health_app(settings, engine, redis_url="redis://fake")

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("down")

    redis.ping = refuse
    redis.llen = refuse
    redis.smembers = refuse
    redis.zcard = refuse
    with browser(app) as admin:
        sign_in(admin, ADMIN)
        body = admin.get("/api/admin/health").json()
    assert body["ready"] is False
    assert body["queue"]["configured"] is True
    assert body["queue"]["reachable"] is False


@respx.mock
def test_the_budget_shows_use_and_whether_calls_wait(settings: Settings, engine: Engine) -> None:
    mock_battle_net()
    small = {"blizzard": (upstream.Window(60, 2),)}
    budget = upstream.Budget(upstream.LocalStore(), budgets=small, sleep=lambda _s: None)
    with browser(health_app(settings, engine)) as admin:
        sign_in(admin, ADMIN)
        upstream.use(budget)  # after the sign-in, which spends Battle.net calls
        before = admin.get("/api/admin/health").json()["budgets"]
        assert before == [
            {"upstream": "blizzard", "window_seconds": 60, "used": 0, "limit": 2, "waiting": False}
        ]
        budget.wait("us.api.blizzard.com")
        budget.wait("us.api.blizzard.com")
        after = admin.get("/api/admin/health").json()["budgets"][0]
    assert after["used"] == 2 and after["waiting"] is True


def test_the_redis_budget_is_read_without_counting() -> None:
    store = upstream.RedisStore(fakeredis.FakeStrictRedis())
    budget = upstream.Budget(store, budgets={"blizzard": (upstream.Window(60, 5),)})
    assert budget.usage()[0].used == 0
    budget.wait("us.api.blizzard.com")
    assert budget.usage()[0].used == 1
    assert budget.usage()[0].used == 1


@respx.mock
def test_leases_held_show_but_cooldowns_do_not(settings: Settings, engine: Engine) -> None:
    mock_battle_net()
    assert leases.acquire(engine, "pool", "me")
    leases.cool_down(engine, "pool", 15)
    with browser(health_app(settings, engine)) as admin:
        sign_in(admin, ADMIN)
        held = admin.get("/api/admin/health").json()["leases"]
    assert [lease["name"] for lease in held] == ["pool"]
    assert "holder" not in held[0]


@respx.mock
def test_a_failed_scheduled_job_is_listed_without_its_secrets(
    settings: Settings, engine: Engine
) -> None:
    mock_battle_net()
    with Session(engine) as session:
        for number in range(30):
            health.record_failure(session, "sync", f"failed: {number}")
        row = session.get(InstanceSetting, health.FAILURES)
        assert row is not None and len(row.value) == health.KEEP_FAILURES
        health.record_failure(session, "pool", f"failed: client_secret={SECRET}")
    with browser(health_app(settings, engine)) as admin:
        sign_in(admin, ADMIN)
        response = admin.get("/api/admin/health")
    assert SECRET not in response.text
    assert json.loads(response.text)["failures"][0]["job"] == "pool"


def test_the_worker_records_a_failing_job(settings: Settings, engine: Engine) -> None:
    def failing(*_args: Any) -> str:
        raise RuntimeError("no luck")

    schedule = worker.Schedule(jobs=[worker.Job("sync", timedelta(hours=1), failing)])
    worker.run_due(engine, settings, schedule, utcnow())
    with Session(engine) as session:
        row = session.get(InstanceSetting, health.FAILURES)
    assert row is not None
    assert row.value[0]["job"] == "sync"
    assert "no luck" in row.value[0]["error"]


def test_without_users_there_is_no_admin_area(settings: Settings, engine: Engine) -> None:
    with browser(create_app(settings, engine)) as client:
        assert client.get("/api/admin/health").status_code == 404
