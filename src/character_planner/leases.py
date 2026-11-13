"""Leases for long refreshes (#87): one at a time, whoever starts it.

The API (a button, or loading data after the first sync), the worker and the background
loader can all start the item pool or enchant refresh. Run twice at once, a refresh
fetches everything twice and goes over Forever Companion's 120 requests a minute. A
lease is a row taken atomically: inserting it, or taking over an expired one, either
succeeds for exactly one process or fails.
"""

import logging
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from character_planner.db import JobLease, utcnow

logger = logging.getLogger(__name__)

# Long enough for a whole-pool refresh (~20 minutes); a process that dies holding a lease
# blocks the refresh for at most this long.
TTL = timedelta(hours=2)
LABELS = {"pool": "item pool", "enchants": "enchant data", "talents": "talent trees"}


class Busy(Exception):
    """The refresh is already running elsewhere."""

    def __init__(self, name: str) -> None:
        super().__init__(f"The {LABELS.get(name, name)} refresh is already running")
        self.name = name


def _holder() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


def acquire(engine: Engine, name: str, holder: str, now: datetime | None = None) -> bool:
    now = now or utcnow()
    with Session(engine) as session:
        session.add(JobLease(name=name, holder=holder, expires_at=now + TTL))
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
        # Held: take it over only if it has expired. One UPDATE, so only one process wins.
        result = session.exec(  # type: ignore[call-overload]
            update(JobLease)
            .where(col(JobLease.name) == name, col(JobLease.expires_at) < now)
            .values(holder=holder, expires_at=now + TTL)
        )
        session.commit()
        return result.rowcount == 1


def release(engine: Engine, name: str, holder: str) -> None:
    with Session(engine) as session:
        lease = session.get(JobLease, name)
        if lease is not None and lease.holder == holder:
            session.delete(lease)
            session.commit()


@contextmanager
def lease(engine: Engine, name: str) -> Iterator[None]:
    """Hold the lease while the block runs; raise Busy if someone else holds it."""
    holder = _holder()
    if not acquire(engine, name, holder):
        raise Busy(name)
    try:
        yield
    finally:
        release(engine, name, holder)


def running(engine: Engine, now: datetime | None = None) -> list[str]:
    """Refreshes running now (unexpired leases), by name."""
    now = now or utcnow()
    with Session(engine) as session:
        rows = session.exec(select(JobLease).where(col(JobLease.expires_at) >= now)).all()
        return sorted(row.name for row in rows)
