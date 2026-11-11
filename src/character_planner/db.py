"""SQLite storage: raw API snapshots, the current OAuth token and the item catalog.

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


class CatalogItem(SQLModel, table=True):
    """Static item data found by name through the item search (ADR 0003).

    found=False is cached too, so items the search can't see aren't re-queried on
    every sync; a forced refresh retries them.
    """

    name_key: str = Field(primary_key=True)  # casefolded item name
    name: str
    found: bool
    item_id: int | None = None
    payload: Any = Field(default=None, sa_column=Column(JSON, nullable=True))
    fetched_at: datetime = Field(default_factory=utcnow)


class ItemIcon(SQLModel, table=True):
    item_id: int = Field(primary_key=True)
    url: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)


def catalog_by_name(session: Session) -> dict[str, CatalogItem]:
    return {row.name_key: row for row in session.exec(select(CatalogItem)).all()}


def icons_by_id(session: Session) -> dict[int, str]:
    return {row.item_id: row.url for row in session.exec(select(ItemIcon)).all() if row.url}


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
