"""First data loads, refresh leases and worker retries (#87)."""

import logging
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, leases, worker
from character_planner.app import create_app
from character_planner.companion import BASE_URL
from character_planner.config import Settings
from character_planner.db import CompanionDungeon, RecipeData, utcnow
from character_planner.dungeons import refresh_dungeons

from .conftest import api_client
from .test_dungeons import LIST


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with api_client(create_app(settings, engine)) as test_client:
        yield test_client


# --- leases ---------------------------------------------------------------------------------


def test_a_lease_is_held_by_one_holder_at_a_time(engine: Engine) -> None:
    assert leases.acquire(engine, "pool", "a")
    assert not leases.acquire(engine, "pool", "b")
    assert leases.running(engine) == ["pool"]
    leases.release(engine, "pool", "b")  # not the holder: nothing happens
    assert leases.running(engine) == ["pool"]
    leases.release(engine, "pool", "a")
    assert leases.running(engine) == []
    assert leases.acquire(engine, "pool", "b")


def test_an_expired_lease_can_be_taken_over(engine: Engine) -> None:
    long_ago = utcnow() - leases.TTL - timedelta(minutes=1)
    assert leases.acquire(engine, "pool", "dead process", now=long_ago)
    assert leases.running(engine) == []  # expired
    assert leases.acquire(engine, "pool", "b")
    assert not leases.acquire(engine, "pool", "c")


def test_the_lease_is_released_even_when_the_refresh_fails(engine: Engine) -> None:
    with pytest.raises(RuntimeError), leases.lease(engine, "enchants"):
        assert leases.running(engine) == ["enchants"]
        raise RuntimeError("refresh broke")
    assert leases.running(engine) == []


def test_a_held_lease_makes_the_refresh_busy(engine: Engine, settings: Settings) -> None:
    assert leases.acquire(engine, "pool", "the worker")
    with Session(engine) as session, pytest.raises(leases.Busy, match="item pool"):
        jobs.refresh_item_pool(session, settings)


def test_the_api_answers_409_while_a_refresh_runs(client: TestClient, engine: Engine) -> None:
    leases.acquire(engine, "pool", "the worker")
    leases.acquire(engine, "enchants", "the worker")
    assert client.get("/api/status").json()["refreshing"] == ["enchants", "pool"]
    pool = client.post("/api/pool/refresh")
    assert pool.status_code == 409 and "already running" in pool.json()["detail"]
    assert client.post("/api/enchants/refresh").status_code == 409


# --- first data load ------------------------------------------------------------------------


def test_missing_data_names_what_a_fresh_instance_lacks(engine: Engine) -> None:
    with Session(engine) as session:
        assert jobs.missing_data(session) == ["pool", "enchants"]
        session.add(CompanionDungeon(dungeon_id="hall-of-thanes", payload={}))
        session.add(RecipeData(recipe_id=1, profession="Enchanting", category="", payload={}))
        session.commit()
        assert jobs.missing_data(session) == []


@respx.mock
def test_the_first_sync_loads_missing_data_in_the_background(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_app import log_in, mock_character_api
    from .test_items import mock_battlenet

    started: list[object] = []
    monkeypatch.setattr(jobs, "load_missing_data", lambda *args: started.append(args))
    log_in(client)
    mock_character_api()
    mock_battlenet()
    assert client.post("/api/sync").status_code == 200
    assert len(started) == 1  # run after the response, by FastAPI's background tasks


def test_the_background_load_skips_a_refresh_already_running(
    engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ran: list[str] = []

    def busy_pool(*_: object, **__: object) -> None:
        raise leases.Busy("pool")

    monkeypatch.setattr(jobs, "refresh_item_pool", busy_pool)
    monkeypatch.setattr(jobs, "refresh_enchants", lambda *_, **__: ran.append("enchants"))
    with caplog.at_level(logging.INFO):
        jobs.load_missing_data(engine, settings)
    assert ran == ["enchants"]  # the busy pool refresh didn't stop the enchant one
    assert "the pool refresh is already running" in caplog.text


# --- worker -----------------------------------------------------------------------------------


def test_a_skipped_job_is_tried_again_in_minutes(engine: Engine, settings: Settings) -> None:
    outcomes = iter(["skipped: no synced level yet", "pool done"])
    job = worker.Job("pool", timedelta(hours=24), lambda *_: next(outcomes))
    schedule = worker.Schedule(jobs=[job])
    start = utcnow()
    assert worker.run_due(engine, settings, schedule, start)["pool"].startswith("skipped")
    assert worker.run_due(engine, settings, schedule, start + timedelta(minutes=1)) == {}
    later = start + worker.RETRY_SKIPPED
    assert worker.run_due(engine, settings, schedule, later) == {"pool": "pool done"}
    # A real run waits the whole interval.
    assert worker.run_due(engine, settings, schedule, later + timedelta(hours=1)) == {}


def test_a_repeated_skip_is_only_logged_at_debug(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    job = worker.Job("sync", timedelta(hours=6), lambda *_: "skipped: no valid login")
    schedule = worker.Schedule(jobs=[job])
    now = utcnow()
    with caplog.at_level(logging.INFO, logger="character_planner.worker"):
        worker.run_due(engine, settings, schedule, now)
        worker.run_due(engine, settings, schedule, now + worker.RETRY_SKIPPED)
    assert caplog.text.count("sync: skipped") == 1


def test_scheduled_refreshes_skip_when_already_running(engine: Engine, settings: Settings) -> None:
    leases.acquire(engine, "enchants", "the API")
    with Session(engine) as session:
        assert worker.enchants_job(session, settings, None) == "skipped: already running"


# --- an empty dungeon list ------------------------------------------------------------------


@respx.mock
def test_an_empty_dungeon_list_is_retried_then_reported(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    route = respx.get(f"{BASE_URL}/dungeons").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    with caplog.at_level(logging.WARNING), Session(engine) as session, httpx.Client() as http:
        outcome = refresh_dungeons(session, http, pause=0)
    assert route.call_count == 2
    assert outcome.errors == ["dungeon list: empty response from Forever Companion"]
    assert (
        "came back empty (attempt 1): HTTP 200, top-level keys ['data', 'meta'], data size 0"
        in caplog.text
    )


@respx.mock
def test_an_empty_list_then_a_good_one_carries_on(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/dungeons").mock(
        side_effect=[httpx.Response(200, json={"data": []}), httpx.Response(200, json=LIST)]
    )
    respx.get(url__startswith=f"{BASE_URL}/dungeons/").mock(return_value=httpx.Response(404))
    with Session(engine) as session, httpx.Client() as http:
        outcome = refresh_dungeons(session, http, pause=0)
    assert outcome.listed > 0
    assert not any("empty" in e for e in outcome.errors)
