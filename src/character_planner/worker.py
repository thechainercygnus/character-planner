"""Scheduled jobs (ADR 0011): sync the character and refresh the item pool on a timer.

Run with: uv run character-planner-worker [--once]

Runs beside the API, sharing its database. Each job runs when its interval has passed
since its last attempt, so a failing job is retried on the next interval, not every
minute. A sync needs the token from the last login: Battle.net gives no refresh token,
so scheduled syncs stop when it expires (24 hours) until you log in again.
"""

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, notify
from character_planner.config import Settings, get_settings
from character_planner.db import init_db, make_engine, utcnow
from character_planner.logs import configure_logging

logger = logging.getLogger("character_planner.worker")

JobFn = Callable[[Session, Settings, httpx.Client | None], str]


def sync_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    try:
        statuses = jobs.sync_character(session, settings, http=http)
    except jobs.NotLoggedIn:
        return "skipped: no valid login (none yet, or it expired); log in to resume syncs"
    failed = sorted(kind for kind, status in statuses.items() if status != 200)
    return f"synced {len(statuses)} endpoints" + (
        f", failed: {', '.join(failed)}" if failed else ""
    )


def pool_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    # Without a level the refresh would fetch the whole pool: hundreds of requests for
    # items far outside the window. Wait for the first sync instead.
    if jobs.character_context(session)[0] is None:
        return "skipped: no synced level yet"
    result = jobs.refresh_item_pool(session, settings, http=http)
    notify.upstream_errors(
        session,
        settings,
        "Item pool refresh",
        result.errors,
        rate_limited=any("rate limited" in e for e in result.errors),
    )
    errors = f", {len(result.errors)} errors" if result.errors else ""
    return (
        f"pool {result.pool_size} items ({result.in_window} in window), "
        f"{result.items_fetched} item details fetched{errors}"
    )


@dataclass
class Job:
    name: str
    every: timedelta
    run: JobFn
    last_run: datetime | None = None

    def due(self, now: datetime) -> bool:
        return self.last_run is None or now - self.last_run >= self.every


@dataclass
class Schedule:
    jobs: list[Job] = field(default_factory=list)


def default_schedule(settings: Settings) -> Schedule:
    """Sync first, so the pool refresh uses the latest level."""
    return Schedule(
        jobs=[
            Job("sync", timedelta(hours=settings.sync_every_hours), sync_job),
            Job("pool", timedelta(hours=settings.pool_every_hours), pool_job),
        ]
    )


def run_due(
    engine: Engine,
    settings: Settings,
    schedule: Schedule,
    now: datetime,
    http: httpx.Client | None = None,
) -> dict[str, str]:
    """Run every job that's due; one failing job never stops the others."""
    outcomes: dict[str, str] = {}
    for job in schedule.jobs:
        if not job.due(now):
            continue
        job.last_run = now
        logger.info("%s: running", job.name)
        try:
            with Session(engine) as session:
                outcomes[job.name] = job.run(session, settings, http)
            logger.info("%s: %s", job.name, outcomes[job.name])
        except Exception as error:
            outcomes[job.name] = f"failed: {error.__class__.__name__}: {error}"
            logger.exception("%s failed", job.name)
            with Session(engine) as session:
                notify.job_failed(session, settings, job.name, outcomes[job.name])
    return outcomes


def tick_notifications(engine: Engine, settings: Settings, http: httpx.Client) -> None:
    """Each pass: warn about an expiring login, then send what's queued (#12)."""
    try:
        with Session(engine) as session:
            notify.check_login(session, settings)
            notify.deliver_due(session, http)
    except Exception:
        logger.exception("Notifications failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run scheduled syncs and pool refreshes.")
    parser.add_argument("--once", action="store_true", help="run every job now, then exit")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings, "worker")
    engine = make_engine(settings.database_url)
    init_db(engine)
    schedule = default_schedule(settings)
    if args.once:
        outcomes = run_due(engine, settings, schedule, utcnow())
        with notify.new_client() as discord:
            tick_notifications(engine, settings, discord)
        return 1 if any(o.startswith("failed") for o in outcomes.values()) else 0

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info(
        "worker started: sync every %sh, pool every %sh",
        settings.sync_every_hours,
        settings.pool_every_hours,
    )
    with notify.new_client() as discord:
        while not stop.is_set():
            run_due(engine, settings, schedule, utcnow())
            tick_notifications(engine, settings, discord)
            stop.wait(settings.worker_poll_seconds)
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
