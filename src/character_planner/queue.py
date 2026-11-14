# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# redis-py and RQ are only partly typed; the code here stays strict otherwise.
"""Background jobs on Redis with RQ (#17, ADR 0039).

Optional: without REDIS_URL, a Sync runs in the web request as it always has. With it, a
Sync is queued as one job per character and worked by `character-planner-jobs`, and the
page polls its state. One character never has two syncs waiting or running at once.
"""

import logging
import re
import sys
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel
from redis import Redis
from rq import Queue, SimpleWorker
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs, upstream
from character_planner.config import get_settings
from character_planner.db import Character, init_db, make_engine
from character_planner.logs import configure_logging

logger = logging.getLogger(__name__)

QUEUE = "planner"
KEEP_RESULT_SECONDS = 3600  # how long a finished sync's outcome stays readable
SYNC_TIMEOUT_SECONDS = 600

State = Literal["idle", "queued", "started", "finished", "failed"]
WAITING = (JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED)


class SyncState(BaseModel):
    """A character's queued sync, as the page polls it."""

    state: State
    result: dict[str, int] | None = None  # endpoint -> HTTP status, once finished
    error: str | None = None


def connect(url: str) -> Redis:
    """The Redis connection; tests swap in fakeredis here."""
    return Redis.from_url(url)


def sync_job_id(character_id: int) -> str:
    return f"sync-{character_id}"


def enqueue_sync(redis: Redis, character_id: int) -> SyncState:
    """Queue a sync for the character, unless one is already waiting or running."""
    queue = Queue(QUEUE, connection=redis)
    job_id = sync_job_id(character_id)
    try:
        existing = Job.fetch(job_id, connection=redis)
        if existing.get_status() in WAITING:
            return sync_state(redis, character_id)
    except NoSuchJobError:
        pass
    queue.enqueue(
        run_sync,
        character_id,
        job_id=job_id,
        job_timeout=SYNC_TIMEOUT_SECONDS,
        result_ttl=KEEP_RESULT_SECONDS,
        failure_ttl=KEEP_RESULT_SECONDS,
    )
    logger.info("Sync queued for character %s", character_id)
    return SyncState(state="queued")


def sync_state(redis: Redis, character_id: int) -> SyncState:
    try:
        job = Job.fetch(sync_job_id(character_id), connection=redis)
    except NoSuchJobError:
        return SyncState(state="idle")
    status = job.get_status()
    if status == JobStatus.FINISHED:
        result: Any = job.return_value()
        return SyncState(state="finished", result=result if isinstance(result, dict) else None)
    if status in (JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED):
        latest = job.latest_result()
        lines = (latest.exc_string or "").strip().splitlines() if latest else []
        return SyncState(state="failed", error=_reason(lines[-1]) if lines else "The sync failed")
    return SyncState(state="started" if status == JobStatus.STARTED else "queued")


def _reason(line: str) -> str:
    """A traceback's last line without its exception's module path, for the page:
    "character_planner.tokens.CredentialsError: no client" becomes "no client"."""
    name, separator, message = line.partition(": ")
    return message if separator and re.fullmatch(r"[\w.]+", name) else line


@cache
def _worker_engine() -> Engine:
    """One engine per jobs process, shared by every job it runs."""
    return make_engine(get_settings().database_url)


def run_sync(character_id: int) -> dict[str, int]:
    """The queued job: sync one character, then load what a fresh instance lacks."""
    settings = get_settings()
    engine = _worker_engine()
    with Session(engine) as session, upstream.client() as http:
        character = session.get(Character, character_id)
        if character is None:
            raise LookupError(f"No character {character_id}: it was deleted")
        statuses = jobs.sync_character(session, settings, character, http=http)
        if jobs.missing_data(session, character_id):
            jobs.load_missing_data(engine, settings, http)
    return statuses


def main() -> int:
    """`character-planner-jobs`: work the queue until stopped. Several can run side by
    side. Jobs run in the worker's own process (RQ's SimpleWorker): it works everywhere,
    Windows included, and jobs share one database connection pool."""
    settings = get_settings()
    configure_logging(settings, "worker")
    if not settings.redis_url:
        print("Set REDIS_URL to run the job worker (ADR 0039)")
        return 2
    init_db(_worker_engine())
    upstream.configure(settings)
    redis = connect(settings.redis_url)
    logger.info("Job worker started on queue %s", QUEUE)
    SimpleWorker([Queue(QUEUE, connection=redis)], connection=redis).work()
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- the admin's refreshes (#17 step 2b) ---------------------------------------------------

Refresh = Literal["pool", "enchants", "items", "talents"]
REFRESHES: tuple[Refresh, ...] = ("pool", "enchants", "items", "talents")
REFRESH_TIMEOUT_SECONDS = 3600  # a whole-pool refresh takes ~20 minutes


def refresh_job_id(kind: Refresh) -> str:
    return f"refresh-{kind}"


def enqueue_refresh(redis: Redis, kind: Refresh, **options: Any) -> SyncState:
    """Queue a refresh, unless one of its kind is already waiting or running."""
    job_id = refresh_job_id(kind)
    try:
        if Job.fetch(job_id, connection=redis).get_status() in WAITING:
            return SyncState(state="queued")
    except NoSuchJobError:
        pass
    Queue(QUEUE, connection=redis).enqueue(
        run_refresh,
        kind,
        options,
        job_id=job_id,
        job_timeout=REFRESH_TIMEOUT_SECONDS,
        result_ttl=KEEP_RESULT_SECONDS,
        failure_ttl=KEEP_RESULT_SECONDS,
    )
    logger.info("Refresh queued: %s", kind)
    return SyncState(state="queued")


def waiting_refreshes(redis: Redis) -> list[str]:
    """Refreshes queued or running on the job queue, for the status bar."""
    waiting: list[str] = []
    for kind in REFRESHES:
        try:
            if Job.fetch(refresh_job_id(kind), connection=redis).get_status() in WAITING:
                waiting.append(kind)
        except NoSuchJobError:
            continue
    return waiting


def run_refresh(kind: Refresh, options: dict[str, Any]) -> dict[str, Any]:
    """The queued job: one of the admin's bulk refreshes, within the upstream budget."""
    from character_planner.items import refresh_item_sources
    from character_planner.leases import Busy

    settings = get_settings()
    engine = _worker_engine()
    character_id: int | None = options.get("character_id")
    force: bool = options.get("force", False)
    with Session(engine) as session, upstream.client() as http:
        try:
            if kind == "pool":
                pool = jobs.refresh_item_pool(
                    session, settings, force=force, http=http, level=options.get("level")
                )
                return pool.model_dump()
            if kind == "enchants":
                return jobs.refresh_enchants(session, settings, force=force, http=http).model_dump()
            if kind == "items":
                return refresh_item_sources(
                    session,
                    settings,
                    jobs.gear_targets(session, settings, character_id),
                    jobs.equipped_item_ids(session, character_id),
                    force=force,
                    http=http,
                ).model_dump()
            talents = jobs.refresh_talents(session, settings, character_id, http=http)
            return talents.model_dump() if talents else {"skipped": "no synced class yet"}
        except Busy as error:
            return {"skipped": str(error)}
