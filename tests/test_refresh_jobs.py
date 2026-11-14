"""The admin's bulk refreshes (#17): rate-limited, and queued when there's a job queue
(ADR 0039). Redis is fakeredis; queued jobs run in a real RQ worker, in burst mode."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import fakeredis
import pytest
from fastapi import FastAPI
from rq import Queue, SimpleWorker
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, leases, queue
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import utcnow
from character_planner.enchants import RecipeRefresh
from character_planner.pool import PoolRefresh

from .conftest import api_client


@pytest.fixture
def fake_refreshes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refreshes that record they ran instead of calling upstream."""
    ran: list[str] = []

    def pool(_session: Session, _settings: Settings, **options: Any) -> PoolRefresh:
        ran.append(f"pool level={options.get('level')}")
        return PoolRefresh(pool_size=10, in_window=4, items_fetched=2)

    def enchants(_session: Session, _settings: Settings, **_: Any) -> RecipeRefresh:
        ran.append("enchants")
        return RecipeRefresh()

    monkeypatch.setattr(jobs, "refresh_item_pool", pool)
    monkeypatch.setattr(jobs, "refresh_enchants", enchants)
    return ran


# --- the cooldown --------------------------------------------------------------------------


def test_a_manual_refresh_waits_its_cooldown(
    settings: Settings, engine: Engine, fake_refreshes: list[str]
) -> None:
    limited = settings.model_copy(update={"refresh_cooldown_minutes": 10})
    with api_client(create_app(limited, engine)) as client:
        assert client.post("/api/pool/refresh").status_code == 200
        again = client.post("/api/pool/refresh")
        assert again.status_code == 429
        assert again.json()["detail"] == "Refreshed recently: again in about 10 minutes"
        assert 9 * 60 < int(again.headers["Retry-After"]) <= 10 * 60 + 1
        # Each refresh has its own cooldown, and a cooldown isn't "refreshing".
        assert client.post("/api/enchants/refresh").status_code == 200
        assert client.get("/api/status").json()["refreshing"] == []
    assert fake_refreshes == ["pool level=None", "enchants"]


def test_the_cooldown_expires_and_can_be_turned_off(engine: Engine) -> None:
    start = utcnow()
    assert leases.cool_down(engine, "pool", 10, now=start) == 0  # starts it
    assert leases.cool_down(engine, "pool", 10, now=start + timedelta(minutes=4)) == 360
    assert leases.cool_down(engine, "pool", 10, now=start + timedelta(minutes=11)) == 0
    assert leases.cool_down(engine, "pool", 0, now=start + timedelta(minutes=12)) == 0
    assert leases.running(engine, now=start + timedelta(minutes=12)) == []


# --- queued refreshes ----------------------------------------------------------------------


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(queue, "connect", lambda _url: fake)
    return fake


@pytest.fixture
def queued(
    settings: Settings, engine: Engine, redis: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    with_redis = settings.model_copy(update={"redis_url": "redis://fake"})
    monkeypatch.setattr(queue, "get_settings", lambda: with_redis)
    monkeypatch.setattr(queue, "_worker_engine", lambda: engine)
    yield create_app(with_redis, engine)


def work(redis: Any) -> None:
    SimpleWorker([Queue(queue.QUEUE, connection=redis)], connection=redis).work(burst=True)


def test_a_queued_refresh_shows_until_the_worker_has_run_it(
    queued: FastAPI, redis: Any, fake_refreshes: list[str]
) -> None:
    with api_client(queued) as client:
        response = client.post("/api/pool/refresh?level=18")
        assert response.status_code == 202
        assert response.json()["state"] == "queued"
        assert client.post("/api/pool/refresh").json()["state"] == "queued"  # still one
        assert Queue(queue.QUEUE, connection=redis).count == 1
        assert client.get("/api/status").json()["refreshing"] == ["pool"]
        assert fake_refreshes == []  # nothing ran in the request

        work(redis)

        assert client.get("/api/status").json()["refreshing"] == []
    assert fake_refreshes == ["pool level=18"]


def test_run_refresh_runs_each_kind(
    settings: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch, fake_refreshes: list[str]
) -> None:
    monkeypatch.setattr(queue, "get_settings", lambda: settings)
    monkeypatch.setattr(queue, "_worker_engine", lambda: engine)
    pool = queue.run_refresh("pool", {"force": True, "level": 20})
    assert (pool["pool_size"], pool["items_fetched"]) == (10, 2)
    assert queue.run_refresh("enchants", {})["recipes_listed"] == 0
    # Talents before any sync: nothing to fetch for.
    assert queue.run_refresh("talents", {"character_id": None}) == {
        "skipped": "no synced class yet"
    }
    assert fake_refreshes == ["pool level=20", "enchants"]


def test_a_refresh_already_running_elsewhere_is_skipped(
    settings: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(*_: Any, **__: Any) -> PoolRefresh:
        raise leases.Busy("pool")

    monkeypatch.setattr(queue, "get_settings", lambda: settings)
    monkeypatch.setattr(queue, "_worker_engine", lambda: engine)
    monkeypatch.setattr(jobs, "refresh_item_pool", busy)
    assert queue.run_refresh("pool", {}) == {"skipped": "The item pool refresh is already running"}
