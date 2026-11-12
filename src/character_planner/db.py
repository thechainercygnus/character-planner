"""SQLite storage: raw API snapshots, the current OAuth token and the item catalog.

Snapshots keep the API's JSON as-is. Typed models come later, built from real
samples, so nothing captured now is lost to a guessed schema (ADR 0002).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, event
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


class CompanionItem(SQLModel, table=True):
    """Raw Forever Companion GET /items/{id} responses (ADR 0004)."""

    item_id: int = Field(primary_key=True)
    found: bool
    payload: Any = Field(default=None, sa_column=Column(JSON, nullable=True))
    fetched_at: datetime = Field(default_factory=utcnow)


class CompanionDungeon(SQLModel, table=True):
    """Raw Forever Companion GET /dungeons/{id} responses: drop tables, quests (ADR 0006)."""

    dungeon_id: str = Field(primary_key=True)  # e.g. "hall-of-thanes"
    payload: Any = Field(sa_column=Column(JSON, nullable=False))
    fetched_at: datetime = Field(default_factory=utcnow)


class RecipeData(SQLModel, table=True):
    """Raw Blizzard GET /data/wow/recipe/{id} responses for enchant recipes (ADR 0010),
    with the profession and skill-tier category they were listed under."""

    recipe_id: int = Field(primary_key=True)
    profession: str
    category: str
    payload: Any = Field(sa_column=Column(JSON, nullable=False))
    fetched_at: datetime = Field(default_factory=utcnow)


class StoredTalentPlan(SQLModel, table=True):
    """The talent plan as edited in the app; data/curated/talent_plan.yaml is the default."""

    id: int = Field(default=1, primary_key=True)
    plan: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class StoredWeights(SQLModel, table=True):
    """Stat weights edited in the app (ADR 0005). One row, id 1; none means defaults."""

    id: int = Field(default=1, primary_key=True)
    weights: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


def catalog_by_name(session: Session) -> dict[str, CatalogItem]:
    return {row.name_key: row for row in session.exec(select(CatalogItem)).all()}


def icons_by_id(session: Session) -> dict[int, str]:
    return {row.item_id: row.url for row in session.exec(select(ItemIcon)).all() if row.url}


# How long a SQLite connection waits for another process's write lock (the app and the
# worker share one file, ADR 0011) before raising "database is locked".
SQLITE_BUSY_TIMEOUT_MS = 10_000


def make_engine(database_url: str) -> Engine:
    if not database_url.startswith("sqlite:///"):
        return create_engine(database_url)
    Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(connection: Any, _record: Any) -> None:
        # WAL lets the API read while the worker writes; NORMAL sync is safe with WAL.
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


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
