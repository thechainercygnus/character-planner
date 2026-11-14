"""Readiness and metrics for running the planner as a service (#17, ADR 0041).

Readiness answers whether this instance can serve: the database answers and its schema is
at the newest migration, and the job queue answers when there is one. Metrics are
Prometheus text, off unless METRICS_TOKEN is set, and then only with that token.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# prometheus-client and redis-py are only partly typed; the code here stays strict otherwise.

from collections.abc import Iterator
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily
from prometheus_client.registry import Collector
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from character_planner import upstream
from character_planner.companion import as_utc
from character_planner.db import MIGRATIONS, Character, Snapshot, User, utcnow

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Readiness(BaseModel):
    ready: bool
    checks: dict[str, str]  # check -> "ok", or what went wrong (the error's type only)


def _head() -> str | None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(config).get_current_head()


def readiness(engine: Engine, redis: Any | None) -> Readiness:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
        checks["database"] = "ok"
        checks["migrations"] = "ok" if current == _head() else f"at {current}, not {_head()}"
    except Exception as error:
        checks["database"] = f"failed: {error.__class__.__name__}"
    if redis is not None:
        try:
            redis.ping()
            checks["queue"] = "ok"
        except Exception as error:
            checks["queue"] = f"failed: {error.__class__.__name__}"
    return Readiness(ready=all(v == "ok" for v in checks.values()), checks=checks)


class _UpstreamWaits(Collector):
    """How often requests waited for the upstream budget (ADR 0040), in this process."""

    def collect(self) -> Iterator[CounterMetricFamily]:
        family = CounterMetricFamily(
            "planner_upstream_budget_waits",
            "Requests that waited for room in an upstream's budget, in this process",
            labels=["upstream"],
        )
        for name, count in sorted(upstream.WAITS.items()):
            family.add_metric([name], count)
        yield family


class Metrics:
    """One registry per app, so tests can build many apps."""

    def __init__(self, version: str) -> None:
        self.registry = CollectorRegistry()
        info = Gauge("planner_info", "The running version", ["version"], registry=self.registry)
        info.labels(version=version).set(1)
        self.requests = Counter(
            "planner_http_requests",
            "HTTP requests, by route template",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "planner_http_request_duration_seconds",
            "How long requests took, by route template",
            ["method", "route"],
            registry=self.registry,
        )
        self.characters = Gauge("planner_characters", "Tracked characters", registry=self.registry)
        self.users = Gauge("planner_users", "Users, with users on", registry=self.registry)
        self.sync_age = Gauge(
            "planner_oldest_sync_age_seconds",
            "Seconds since the least recently synced character's last sync",
            registry=self.registry,
        )
        self.jobs = Gauge(
            "planner_queue_jobs", "Jobs on the queue, by state", ["state"], registry=self.registry
        )
        self.registry.register(_UpstreamWaits())

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests.labels(method=method, route=route, status=str(status)).inc()
        self.duration.labels(method=method, route=route).observe(seconds)

    def render(self, engine: Engine, redis: Any | None) -> bytes:
        """The current numbers, read at scrape time."""
        with Session(engine) as session:
            self.characters.set(session.exec(select(func.count()).select_from(Character)).one())
            self.users.set(session.exec(select(func.count()).select_from(User)).one())
            last_syncs = session.exec(
                select(func.max(Snapshot.captured_at))
                .where(col(Snapshot.source) == "api", col(Snapshot.character_id).is_not(None))
                .group_by(col(Snapshot.character_id))
            ).all()
        now = utcnow()
        ages = [(now - as_utc(moment)).total_seconds() for moment in last_syncs if moment]
        self.sync_age.set(max(ages) if ages else 0)
        if redis is not None:
            from rq import Queue
            from rq.registry import FailedJobRegistry, StartedJobRegistry

            from character_planner.queue import QUEUE

            queue = Queue(QUEUE, connection=redis)
            self.jobs.labels(state="queued").set(queue.count)
            self.jobs.labels(state="started").set(StartedJobRegistry(queue=queue).count)
            self.jobs.labels(state="failed").set(FailedJobRegistry(queue=queue).count)
        return generate_latest(self.registry)
