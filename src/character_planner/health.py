"""Instance health for the admin area (#241): what `/api/readyz` and the metrics (ADR 0041)
already know, read directly so it works without METRICS_TOKEN, behind the admin's sign-in.

Nothing here carries a token, a secret or another user's data: failures name the kind of job
and its error with `logs.redact` applied, never a character, an account or a payload.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# redis-py and RQ are only partly typed; the code here stays strict otherwise.

from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from character_planner import leases, upstream
from character_planner.db import (
    BlizzardItem,
    CompanionItem,
    CraftingRecipe,
    InstanceSetting,
    JobLease,
    RecipeData,
    TalentTreeData,
    utcnow,
)
from character_planner.logs import redact
from character_planner.metrics import readiness

FAILURES: Final = "job_failures"  # the scheduled worker's recent failures, in InstanceSetting
KEEP_FAILURES: Final = 20
MAX_ERROR: Final = 300


class Failure(BaseModel):
    job: str  # "sync", "refresh pool", "enchants" ...
    at: datetime | None = None
    error: str


class QueueHealth(BaseModel):
    configured: bool
    reachable: bool = False
    queued: int = 0
    started: int = 0
    failed: int = 0
    workers: int = 0
    last_heartbeat: datetime | None = None


class BudgetHealth(BaseModel):
    upstream: str
    window_seconds: int
    used: int
    limit: int
    waiting: bool  # the window is full: further calls wait for the next one


class Refresh(BaseModel):
    name: str
    last: datetime | None = None  # when something in this catalog was last fetched


class Lease(BaseModel):
    name: str
    expires_at: datetime


class DatabaseHealth(BaseModel):
    reachable: bool
    migrated: bool


class Health(BaseModel):
    ready: bool
    database: DatabaseHealth
    queue: QueueHealth
    failures: list[Failure]
    budgets: list[BudgetHealth]
    refreshes: list[Refresh]
    leases: list[Lease]


def _clean(text: str) -> str:
    return redact(text)[:MAX_ERROR]


def record_failure(session: Session, job: str, error: str, now: datetime | None = None) -> None:
    """The worker notes a failed scheduled job, newest first, for the admin area."""
    row = session.get(InstanceSetting, FAILURES) or InstanceSetting(key=FAILURES, value=[])
    entry = Failure(job=job, at=now or utcnow(), error=_clean(error)).model_dump(mode="json")
    row.value = [entry, *list(row.value)][:KEEP_FAILURES]
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def _worker_failures(session: Session) -> list[Failure]:
    row = session.get(InstanceSetting, FAILURES)
    return [Failure.model_validate(item) for item in (row.value if row else [])]


def _queue(redis: Any | None) -> tuple[QueueHealth, list[Failure]]:
    if redis is None:
        return QueueHealth(configured=False), []
    from rq import Queue, Worker
    from rq.job import Job
    from rq.registry import FailedJobRegistry, StartedJobRegistry

    from character_planner.queue import QUEUE, reason

    try:
        queue = Queue(QUEUE, connection=redis)
        failed = FailedJobRegistry(queue=queue)
        workers = Worker.all(connection=redis, queue=queue)
        beats = [w.last_heartbeat for w in workers if w.last_heartbeat]
        failures: list[Failure] = []
        for job in Job.fetch_many(failed.get_job_ids(), connection=redis):
            if job is None:
                continue
            latest = job.latest_result()
            lines = (latest.exc_string or "").strip().splitlines() if latest else []
            # "sync-12" names a character: keep the kind only.
            kind = job.id.split("-", 1)
            name = "sync" if kind[0] == "sync" else f"refresh {kind[-1]}"
            failures.append(
                Failure(
                    job=name,
                    at=job.ended_at,
                    error=_clean(reason(lines[-1]) if lines else "The job failed"),
                )
            )
        failures.sort(key=lambda f: f.at or datetime.min, reverse=True)
        health = QueueHealth(
            configured=True,
            reachable=True,
            queued=queue.count,
            started=StartedJobRegistry(queue=queue).count,
            failed=failed.count,
            workers=len(workers),
            last_heartbeat=max(beats) if beats else None,
        )
        return health, failures
    except Exception:
        return QueueHealth(configured=True, reachable=False), []


def _refreshes(session: Session) -> list[Refresh]:
    catalogs: list[tuple[str, Any]] = [
        ("Item pool", CompanionItem.fetched_at),
        ("Enchants", RecipeData.fetched_at),
        ("Recipes", CraftingRecipe.fetched_at),
        ("Game items", BlizzardItem.fetched_at),
        ("Talent trees", TalentTreeData.fetched_at),
    ]
    return [
        Refresh(name=name, last=session.exec(select(func.max(column))).one())
        for name, column in catalogs
    ]


def instance_health(session: Session, engine: Engine, redis: Any | None) -> Health:
    ready = readiness(engine, redis)
    queue, queue_failures = _queue(redis)
    failures = sorted(
        [*queue_failures, *_worker_failures(session)],
        key=lambda f: f.at.replace(tzinfo=None) if f.at else datetime.min,
        reverse=True,
    )
    now = utcnow()
    held = [
        Lease(name=row.name, expires_at=row.expires_at)
        for row in session.exec(
            select(JobLease).where(col(JobLease.expires_at) >= now).order_by(col(JobLease.name))
        ).all()
        if not row.name.startswith(leases.COOLDOWN)
    ]
    return Health(
        ready=ready.ready,
        database=DatabaseHealth(
            reachable=ready.checks.get("database") == "ok",
            migrated=ready.checks.get("migrations") == "ok",
        ),
        queue=queue,
        failures=failures,
        budgets=[
            BudgetHealth(
                upstream=u.upstream,
                window_seconds=u.window_seconds,
                used=u.used,
                limit=u.limit,
                waiting=u.used >= u.limit,
            )
            for u in upstream.usage()
        ],
        refreshes=_refreshes(session),
        leases=held,
    )
