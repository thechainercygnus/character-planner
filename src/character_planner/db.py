"""SQLite storage: raw API snapshots and the current OAuth token.

Snapshots keep the API's JSON as-is. Typed models come later, built from real
samples, so nothing captured now is lost to a guessed schema (ADR 0002).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, col, create_engine, desc, select


def utcnow() -> datetime:
    return datetime.now(UTC)


class Snapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    captured_at: datetime = Field(default_factory=utcnow, index=True)
    source: str = Field(index=True)  # "api" or "manual"
    kind: str = Field(index=True)  # e.g. "profile", "equipment"
    status: int  # HTTP status for API pulls; 200 for manual entries
    payload: Any = Field(sa_column=Column(JSON, nullable=True))


class StoredToken(SQLModel, table=True):
    """The single user token. One row, id 1: this is a one-user app."""

    id: int = Field(default=1, primary_key=True)
    access_token: str
    expires_at: float
    scope: str = ""


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def latest_by_kind(session: Session) -> dict[str, Snapshot]:
    """Newest successful snapshot of each kind."""
    rows = session.exec(
        select(Snapshot)
        .where(col(Snapshot.status) >= 200, col(Snapshot.status) < 300)
        .order_by(desc(col(Snapshot.captured_at)), desc(col(Snapshot.id)))
    ).all()
    latest: dict[str, Snapshot] = {}
    for row in rows:
        latest.setdefault(row.kind, row)
    return latest
