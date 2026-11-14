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
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from character_planner.companion import as_utc
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


def acquire(
    engine: Engine, name: str, holder: str, now: datetime | None = None, ttl: timedelta = TTL
) -> bool:
    now = now or utcnow()
    with Session(engine) as session:
        session.add(JobLease(name=name, holder=holder, expires_at=now + ttl))
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
        # Held: take it over only if it has expired. One UPDATE, so only one process wins.
        result = session.exec(  # type: ignore[call-overload]
            update(JobLease)
            .where(col(JobLease.name) == name, col(JobLease.expires_at) < now)
            .values(holder=holder, expires_at=now + ttl)
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
def lease(engine: Engine, name: str) -> Generator[None]:
    """Hold the lease while the block runs; raise Busy if someone else holds it."""
    holder = _holder()
    if not acquire(engine, name, holder):
        raise Busy(name)
    try:
        yield
    finally:
        release(engine, name, holder)


def running(engine: Engine, now: datetime | None = None) -> list[str]:
    """Refreshes running now (unexpired leases), by name. Cooldowns aren't refreshes."""
    now = now or utcnow()
    with Session(engine) as session:
        rows = session.exec(select(JobLease).where(col(JobLease.expires_at) >= now)).all()
        return sorted(row.name for row in rows if not row.name.startswith(COOLDOWN))


COOLDOWN = "cooldown:"


def cool_down(engine: Engine, name: str, minutes: float, now: datetime | None = None) -> float:
    """A manual refresh's rate limit (#17): 0 when it may start, which starts its cooldown,
    else the seconds left. Kept as a lease that's never released, so every process sees
    it and it simply expires."""
    if minutes <= 0:
        return 0
    now = now or utcnow()
    key = f"{COOLDOWN}{name}"
    if acquire(engine, key, _holder(), now, timedelta(minutes=minutes)):
        return 0
    with Session(engine) as session:
        held = session.get(JobLease, key)
        left = (as_utc(held.expires_at) - now).total_seconds() if held else 0
    return max(left, 0.0)
