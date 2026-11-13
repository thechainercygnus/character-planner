"""Scheduled jobs (ADR 0011): sync the character and refresh the item pool on a timer.

Run with: uv run character-planner-worker [--once]

Runs beside the API, sharing its database. Each job runs when its interval has passed
since its last attempt, so a failing job is retried on the next interval, not every
minute. Syncs use the app's own Battle.net token (tokens.py, #107), so they keep running
with no login.
"""

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import FrameType

import httpx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, notify
from character_planner.config import Settings, get_settings
from character_planner.db import init_db, make_engine, utcnow
from character_planner.leases import Busy
from character_planner.logs import configure_logging

logger = logging.getLogger("character_planner.worker")

# How soon a skipped job (no client yet, no level yet, already running) is tried again.
RETRY_SKIPPED = timedelta(minutes=2)

JobFn = Callable[[Session, Settings, httpx.Client | None], str]


def sync_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    # Syncs use the app's own token (#107): no login needed. Without a client at all
    # (guest mode only), there's nothing to sync with. A client Battle.net refuses raises
    # CredentialsError, which fails the job and sends the system alert.
    if not settings.has_credentials:
        return "skipped: no Battle.net client (BNET_CLIENT_ID, BNET_CLIENT_SECRET in .env)"
    statuses = jobs.sync_character(session, settings, http=http)
    if statuses.get("profile") == 404:
        return f"character {settings.character_slug} not found: check its name and region"
    failed = sorted(kind for kind, status in statuses.items() if status != 200)
    return f"synced {len(statuses)} endpoints" + (
        f", failed: {', '.join(failed)}" if failed else ""
    )


def pool_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    # Without a level the refresh would fetch the whole pool: hundreds of requests for
    # items far outside the window. Wait for the first sync instead.
    if jobs.character_context(session)[0] is None:
        return "skipped: no synced level yet"
    try:
        result = jobs.refresh_item_pool(session, settings, http=http)
    except Busy:
        return "skipped: already running"
    notify_upstream(session, settings, "Item pool refresh", result.errors)
    errors = f", {len(result.errors)} errors" if result.errors else ""
    return (
        f"pool {result.pool_size} items ({result.in_window} in window), "
        f"{result.items_fetched} item details fetched{errors}"
    )


def enchants_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    try:
        result = jobs.refresh_enchants(session, settings, http=http)
    except Busy:
        return "skipped: already running"
    notify_upstream(session, settings, "Enchant data refresh", result.errors)
    return (
        f"{result.recipes_listed} enchant recipes ({result.recipes_fetched} fetched), "
        f"{result.items_fetched} reagent and crafted item details fetched"
        + (f", {len(result.errors)} errors" if result.errors else "")
    )


def talents_job(session: Session, settings: Settings, http: httpx.Client | None) -> str:
    try:
        result = jobs.refresh_talents(session, settings, http=http)
    except Busy:
        return "skipped: already running"
    if result is None:
        return "skipped: no synced class yet"
    notify_upstream(session, settings, "Talent tree refresh", result.errors)
    return f"{result.class_name}: {result.trees} talent trees, {result.icons} icons" + (
        f", {len(result.errors)} errors" if result.errors else ""
    )


def notify_upstream(session: Session, settings: Settings, job: str, errors: list[str]) -> None:
    """A system alert for many upstream errors, or for one that stopped the refresh: a
    rate limit, or an upstream list that came back empty (#87)."""
    urgent = any("rate limited" in e or "empty" in e for e in errors)
    notify.upstream_errors(session, settings, job, errors, rate_limited=urgent)


@dataclass
class Job:
    name: str
    every: timedelta
    run: JobFn
    last_run: datetime | None = None
    last_outcome: str | None = None

    def due(self, now: datetime) -> bool:
        return self.last_run is None or now - self.last_run >= self.every


@dataclass
class Schedule:
    jobs: list[Job] = field(default_factory=list[Job])


def default_schedule(settings: Settings) -> Schedule:
    """Sync first, so the pool refresh uses the latest level."""
    return Schedule(
        jobs=[
            Job("sync", timedelta(hours=settings.sync_every_hours), sync_job),
            Job("pool", timedelta(hours=settings.pool_every_hours), pool_job),
            Job("enchants", timedelta(hours=settings.enchants_every_hours), enchants_job),
            # Talent trees are static too: on the enchants' weekly schedule (#88).
            Job("talents", timedelta(hours=settings.enchants_every_hours), talents_job),
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
        repeat_skip = (job.last_outcome or "").startswith("skipped")
        logger.log(logging.DEBUG if repeat_skip else logging.INFO, "%s: running", job.name)
        try:
            with Session(engine) as session:
                outcome = job.run(session, settings, http)
            outcomes[job.name] = outcome
            if outcome.startswith("skipped"):
                # Not a run: try again soon, so a new client or first sync is picked up in
                # minutes rather than a whole interval later (#87).
                job.last_run = now - job.every + RETRY_SKIPPED
            # The same outcome again (a skip every few minutes) only at DEBUG.
            level = logging.DEBUG if outcome == job.last_outcome else logging.INFO
            logger.log(level, "%s: %s", job.name, outcome)
            job.last_outcome = outcome
        except Exception as error:
            outcomes[job.name] = f"failed: {error.__class__.__name__}: {error}"
            logger.exception("%s failed", job.name)
            with Session(engine) as session:
                notify.job_failed(session, settings, job.name, outcomes[job.name])
    return outcomes


def tick_notifications(engine: Engine, settings: Settings, http: httpx.Client) -> None:
    """Each pass: send what's queued (#12)."""
    try:
        with Session(engine) as session:
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
    try:
        return run(engine, settings, once=args.once)
    finally:
        engine.dispose()


def run(engine: Engine, settings: Settings, *, once: bool) -> int:
    """The worker loop, or one pass of it with once=True."""
    init_db(engine)
    schedule = default_schedule(settings)
    if once:
        outcomes = run_due(engine, settings, schedule, utcnow())
        with notify.new_client() as discord:
            tick_notifications(engine, settings, discord)
        return 1 if any(o.startswith("failed") for o in outcomes.values()) else 0

    stop = threading.Event()

    def stop_on_signal(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_on_signal)
    signal.signal(signal.SIGINT, stop_on_signal)
    logger.info(
        "worker started: sync every %sh, pool every %sh, enchants every %sh",
        settings.sync_every_hours,
        settings.pool_every_hours,
        settings.enchants_every_hours,
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
