import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs, worker
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import Snapshot, StoredToken
from character_planner.pool import PoolRefresh

from .conftest import tracked
from .test_app import mock_character_api

START = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)


def store_token(engine: Engine, expires_in: float) -> None:
    with Session(engine) as session:
        session.merge(
            StoredToken(
                id=1, access_token="tok", expires_at=time.time() + expires_in, scope="wow.profile"
            )
        )
        session.commit()


def counting(name: str, calls: list[str]) -> worker.JobFn:
    def run(_session: Session, _settings: Settings, _http: httpx.Client | None) -> str:
        calls.append(name)
        return f"{name} ok"

    return run


def test_jobs_run_when_their_interval_has_passed(engine: Engine, settings: Settings) -> None:
    calls: list[str] = []
    schedule = worker.Schedule(
        jobs=[
            worker.Job("sync", timedelta(hours=6), counting("sync", calls)),
            worker.Job("pool", timedelta(hours=24), counting("pool", calls)),
        ]
    )

    assert worker.run_due(engine, settings, schedule, START) == {
        "sync": "sync ok",
        "pool": "pool ok",
    }  # both run on start
    assert worker.run_due(engine, settings, schedule, START + timedelta(hours=5)) == {}
    assert list(worker.run_due(engine, settings, schedule, START + timedelta(hours=6))) == ["sync"]
    assert list(worker.run_due(engine, settings, schedule, START + timedelta(hours=24))) == [
        "sync",
        "pool",
    ]
    assert calls == ["sync", "pool", "sync", "sync", "pool"]


def test_a_failing_job_waits_its_interval_and_never_stops_the_others(
    engine: Engine, settings: Settings
) -> None:
    calls: list[str] = []

    def broken(_session: Session, _settings: Settings, _http: httpx.Client | None) -> str:
        raise RuntimeError("Forever Companion is down")

    schedule = worker.Schedule(
        jobs=[
            worker.Job("pool", timedelta(hours=24), broken),
            worker.Job("sync", timedelta(hours=6), counting("sync", calls)),
        ]
    )
    outcomes = worker.run_due(engine, settings, schedule, START)
    assert outcomes["pool"] == "failed: RuntimeError: Forever Companion is down"
    assert outcomes["sync"] == "sync ok"
    # Not retried every minute: the next attempt waits for the interval.
    assert "pool" not in worker.run_due(engine, settings, schedule, START + timedelta(minutes=1))


def test_default_schedule_comes_from_settings(settings: Settings) -> None:
    custom = settings.model_copy(update={"sync_every_hours": 2, "pool_every_hours": 12})
    schedule = worker.default_schedule(custom)
    assert [(j.name, j.every) for j in schedule.jobs] == [
        ("sync", timedelta(hours=2)),
        ("pool", timedelta(hours=12)),
        ("enchants", timedelta(hours=168)),
        ("talents", timedelta(hours=168)),
        ("retention", timedelta(hours=24)),  # Blizzard data past 30 days (#131)
    ]


@respx.mock
def test_scheduled_sync_stores_snapshots_even_with_an_expired_login(
    engine: Engine, settings: Settings
) -> None:
    store_token(engine, -10)  # the 24-hour login has expired: syncs carry on (#107)
    mock_character_api()
    respx.post(oauth.TOKEN_URL).mock(  # the app's own token, for the sync and lookups
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.route().mock(return_value=httpx.Response(404, json={"error": "Not found"}))

    with Session(engine) as session, httpx.Client() as http:
        outcome = worker.sync_job(session, settings, http)
        kinds = {s.kind for s in session.exec(select(Snapshot)).all()}

    served = {"profile", "equipment", "statistics", "professions", "specializations"}
    assert served <= kinds
    # Endpoints the mock doesn't serve (404) are stored and named as failed.
    assert outcome == (
        f"brumboldt-doomlet synced {len(kinds)} endpoints, "
        f"failed: {', '.join(sorted(kinds - served))}"
    )


@respx.mock  # no routes: any request would fail the test
def test_pool_refresh_waits_for_a_synced_level(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session, httpx.Client() as http:
        assert worker.pool_job(session, settings, http) == "skipped: no synced level yet"


def test_pool_refresh_runs_once_a_level_is_synced(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    levels: list[int | None] = []

    def fake_refresh(session: Session, _settings: Settings, **_: object) -> PoolRefresh:
        levels.append(jobs.character_context(session, jobs.current_id(session))[0])
        return PoolRefresh(pool_size=120, in_window=40, items_fetched=3)

    monkeypatch.setattr(jobs, "refresh_item_pool", fake_refresh)
    with Session(engine) as session:
        session.add(
            Snapshot(
                character_id=tracked(session),
                source="api",
                kind="profile",
                status=200,
                payload={"level": 19},
            )
        )
        session.commit()
        outcome = worker.pool_job(session, settings, None)
    assert levels == [19]
    assert outcome == "pool 120 items (40 in window), 3 item details fetched"


def test_once_runs_every_job_and_exits(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "sync_job", counting("sync", calls))
    monkeypatch.setattr(worker, "pool_job", counting("pool", calls))
    assert worker.main(["--once"]) == 0
    assert calls == ["sync", "pool"]
