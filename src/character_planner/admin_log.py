"""The admin action log (#238, ADR 0056): what the admin area did, who did it, to whom.

It's the operator's record that a data request was handled: a deletion, an export, a role
change, a correction to shared data. Each entry holds Battle.net account ids, the action
and a short detail, never the data itself. Entries outlive the accounts they name, since
a deletion's entry is the proof it happened. They're kept for a year (KEEP), then pruned
by the worker's daily retention job.
"""

import logging
from datetime import datetime, timedelta
from typing import Final

from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, col, select

from character_planner.db import AdminAction, utcnow

logger = logging.getLogger(__name__)

KEEP: Final = timedelta(days=365)
LIMIT: Final = 200  # entries the admin area shows, newest first


class Entry(BaseModel):
    id: int
    at: datetime
    actor_account_id: int | None  # None: the command line
    action: str
    target_account_id: int | None
    detail: str | None


def record(
    session: Session,
    action: str,
    *,
    actor: int | None,
    target: int | None = None,
    detail: str | None = None,
    commit: bool = True,
) -> None:
    """Log an action; `actor` and `target` are Battle.net account ids."""
    session.add(
        AdminAction(actor_account_id=actor, action=action, target_account_id=target, detail=detail)
    )
    if commit:
        session.commit()


def recent(session: Session, limit: int = LIMIT) -> list[Entry]:
    rows = session.exec(
        select(AdminAction)
        .order_by(col(AdminAction.at).desc(), col(AdminAction.id).desc())
        .limit(limit)
    ).all()
    return [Entry.model_validate(row, from_attributes=True) for row in rows]


def prune(session: Session) -> int:
    """Delete entries older than KEEP; how many."""
    result = session.exec(delete(AdminAction).where(col(AdminAction.at) < utcnow() - KEEP))  # pyright: ignore[reportCallIssue, reportArgumentType]
    session.commit()
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        logger.info("Admin log: pruned %d entries older than a year", count)
    return count
