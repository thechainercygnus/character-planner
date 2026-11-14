"""Syncs as background jobs, and how often a character may be synced by hand (#17,
ADR 0039). Redis is fakeredis; the jobs run in a real RQ worker, in burst mode."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import fakeredis
import httpx
import pytest
import respx
from fastapi import FastAPI
from rq import Queue, SimpleWorker
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import queue
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import Snapshot, utcnow

from .conftest import api_client, tracked
from .test_app import mock_character_api


def mock_battle_net() -> None:
    mock_character_api()
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.route().mock(return_value=httpx.Response(404, json={"error": "Not found"}))


# --- the cooldown --------------------------------------------------------------------------


def stored_sync(engine: Engine, minutes_ago: float) -> int:
    with Session(engine) as session:
        me = tracked(session)
        session.add(
            Snapshot(
                character_id=me,
                source="api",
                kind="profile",
                status=200,
                payload={"level": 19},
                captured_at=utcnow() - timedelta(minutes=minutes_ago),
            )
        )
        session.commit()
        return me


def test_a_character_synced_recently_waits(settings: Settings, engine: Engine) -> None:
    stored_sync(engine, minutes_ago=5)  # by the worker, say
    strict = settings.model_copy(update={"sync_cooldown_minutes": 15})
    with api_client(create_app(strict, engine)) as client:
        response = client.post("/api/sync")
    assert response.status_code == 429
    assert response.json()["detail"] == "Synced recently: sync again in about 10 minutes"
    assert 9 * 60 < int(response.headers["Retry-After"]) <= 10 * 60 + 1


@respx.mock
def test_after_the_cooldown_it_syncs(settings: Settings, engine: Engine) -> None:
    mock_battle_net()
    stored_sync(engine, minutes_ago=16)
    strict = settings.model_copy(update={"sync_cooldown_minutes": 15})
    with api_client(create_app(strict, engine)) as client:
        assert client.post("/api/sync").status_code == 200
        assert client.post("/api/sync").status_code == 429  # it just synced


def test_the_cooldown_counts_per_character(engine: Engine) -> None:
    from character_planner import jobs
    from character_planner.db import Character

    me = stored_sync(engine, minutes_ago=1)
    with Session(engine) as session:
        other = Character(region="eu", slug="someone-else", name="Someone", surname="Else")
        session.add(other)
        session.commit()
        assert other.id is not None
        assert jobs.sync_cooldown_left(session, me, 15) > 0
        assert jobs.sync_cooldown_left(session, other.id, 15) == 0
        assert jobs.sync_cooldown_left(session, me, 0) == 0  # turned off


# --- queued syncs --------------------------------------------------------------------------


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(queue, "connect", lambda _url: fake)
    return fake


@pytest.fixture
def queued(
    settings: Settings, engine: Engine, redis: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    """The app with a queue, and jobs that run against the test database."""
    with_redis = settings.model_copy(update={"redis_url": "redis://fake"})
    monkeypatch.setattr(queue, "get_settings", lambda: with_redis)
    monkeypatch.setattr(queue, "_worker_engine", lambda: engine)
    yield create_app(with_redis, engine)


def work(redis: Any) -> None:
    """Run every queued job, as `character-planner-jobs` would, then stop."""
    SimpleWorker([Queue(queue.QUEUE, connection=redis)], connection=redis).work(burst=True)


@respx.mock
def test_a_queued_sync_is_followed_until_it_finishes(
    queued: FastAPI, engine: Engine, redis: Any
) -> None:
    mock_battle_net()
    with api_client(queued) as client:
        assert client.get("/api/sync").json() == {"state": "idle", "result": None, "error": None}
        response = client.post("/api/sync")
        assert response.status_code == 202
        assert response.json()["state"] == "queued"
        # Clicked again while it waits: still the one job.
        assert client.post("/api/sync").json()["state"] == "queued"
        assert Queue(queue.QUEUE, connection=redis).count == 1
        assert client.get("/api/sync").json()["state"] == "queued"

        work(redis)

        done = client.get("/api/sync").json()
        assert done["state"] == "finished"
        assert done["result"]["profile"] == 200
        assert client.get("/api/character").json()["level"] == 18  # stored by the job
    with Session(engine) as session:
        assert {s.character_id for s in session.exec(select(Snapshot)).all()} == {1}


def test_a_failed_job_says_why(queued: FastAPI, engine: Engine, redis: Any) -> None:
    """A character deleted while its sync waited: the job fails, and says so."""
    with api_client(queued) as client:
        client.post("/api/sync")
        client.delete("/api/character")  # gone before the worker gets to it
        work(redis)
        state = queue.sync_state(redis, 1)
    assert state.state == "failed"
    assert state.error == "No character 1: it was deleted"  # no exception class or module


def test_the_job_worker_needs_redis(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "get_settings", lambda: settings)
    monkeypatch.setattr(queue, "configure_logging", lambda *_: None)
    assert queue.main() == 2


def test_the_worker_keeps_a_job_worker_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """With REDIS_URL the worker container runs the job worker as a child (ADR 0039),
    starts it again if it exits, and stops it with itself."""
    import sys
    import time

    from character_planner.worker import JobsWorker

    jobs_worker = JobsWorker()
    monkeypatch.setattr(JobsWorker, "COMMAND", (sys.executable, "-c", "pass"))
    jobs_worker.keep_running()
    first = jobs_worker.process
    assert first is not None
    first.wait(timeout=30)
    jobs_worker.keep_running()  # it exited: started again
    assert jobs_worker.process is not None and jobs_worker.process.pid != first.pid
    jobs_worker.process.wait(timeout=30)

    monkeypatch.setattr(
        JobsWorker, "COMMAND", (sys.executable, "-c", "import time; time.sleep(60)")
    )
    jobs_worker.keep_running()
    running = jobs_worker.process
    assert running is not None
    jobs_worker.keep_running()  # still running: left alone
    assert jobs_worker.process is running
    started = time.monotonic()
    jobs_worker.stop()
    assert running.poll() is not None and time.monotonic() - started < 30
