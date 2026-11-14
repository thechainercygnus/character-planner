"""Readiness and metrics for running it as a service (#17, ADR 0041)."""

from typing import Any

import fakeredis
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import queue, upstream
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import Snapshot, utcnow
from character_planner.metrics import readiness

from .conftest import api_client, tracked

TOKEN = "scrape-me"


def test_ready_when_the_database_is_at_the_newest_migration(
    settings: Settings, engine: Engine
) -> None:
    with api_client(create_app(settings, engine)) as client:
        response = client.get("/api/readyz")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "checks": {"database": "ok", "migrations": "ok"}}


def test_not_ready_on_an_old_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0011'"))
    ready = readiness(engine, None)
    assert not ready.ready
    assert ready.checks["migrations"].startswith("at 0011, not ")


def test_not_ready_without_the_queue(engine: Engine) -> None:
    class Down:
        def ping(self) -> None:
            raise ConnectionError("no route to valkey")

    ready = readiness(engine, Down())
    assert not ready.ready
    assert ready.checks["queue"] == "failed: ConnectionError"  # the type, no internals
    assert readiness(engine, fakeredis.FakeStrictRedis()).checks["queue"] == "ok"


def test_metrics_are_off_without_a_token(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/metrics").status_code == 404


def test_metrics_need_the_token(settings: Settings, engine: Engine) -> None:
    on = settings.model_copy(update={"metrics_token": SecretStr(TOKEN)})
    with api_client(create_app(on, engine)) as client:
        refused = client.get("/api/metrics", headers={"Authorization": "Bearer wrong"})
        assert refused.status_code == 401
        assert refused.headers["WWW-Authenticate"] == "Bearer"
        assert client.get("/api/metrics").status_code == 401


@pytest.fixture
def scraped(settings: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Any]:
    """Metrics after some traffic, with a queue that has a job waiting."""
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(queue, "connect", lambda _url: fake)
    monkeypatch.setattr(upstream, "WAITS", {"forevercompanion": 3})
    with Session(engine) as session:
        session.add(
            Snapshot(
                character_id=tracked(session),
                source="api",
                kind="profile",
                status=200,
                payload={"level": 19},
                captured_at=utcnow(),
            )
        )
        session.commit()
    on = settings.model_copy(
        update={"metrics_token": SecretStr(TOKEN), "redis_url": "redis://fake"}
    )
    with api_client(create_app(on, engine)) as client:
        client.get("/api/character")
        client.get("/api/choices")
        client.post("/api/sync")  # queued: one job waiting
        response = client.get("/api/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return response.text, fake


def test_metrics_count_requests_by_route_template(scraped: tuple[str, Any]) -> None:
    body, _ = scraped
    assert (
        'planner_http_requests_total{method="GET",route="/api/character",status="200"} 1.0' in body
    )
    assert 'planner_http_request_duration_seconds_count{method="GET",route="/api/choices"}' in body
    assert "planner_info{" in body


def test_metrics_report_characters_syncs_queue_and_budget(scraped: tuple[str, Any]) -> None:
    body, _ = scraped
    assert "planner_characters 1.0" in body
    assert "planner_users 0.0" in body
    age = next(line for line in body.splitlines() if line.startswith("planner_oldest_sync_age"))
    assert float(age.split()[1]) < 60
    assert 'planner_queue_jobs{state="queued"} 1.0' in body
    assert 'planner_upstream_budget_waits_total{upstream="forevercompanion"} 3.0' in body
    assert TOKEN not in body
