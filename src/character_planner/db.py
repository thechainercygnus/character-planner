"""SQLite storage: raw API snapshots, the current OAuth token and the item catalog.

Snapshots keep the API's JSON as-is. Typed models come later, built from real
samples, so nothing captured now is lost to a guessed schema (ADR 0002).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint, event
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


class StoredUsageRules(SQLModel, table=True):
    """The Upgrades rules as edited in the app (ADR 0016); data/curated/recommend.yaml is
    the default. One row, id 1; none means the YAML."""

    id: int = Field(default=1, primary_key=True)
    rules: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class StoredGearTargets(SQLModel, table=True):
    """Gear targets edited in the app (ADR 0014); data/curated/gear_targets.yaml is the
    default. One row, id 1; none means the YAML."""

    id: int = Field(default=1, primary_key=True)
    targets: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class StoredWeights(SQLModel, table=True):
    """Stat weights edited in the app before presets (ADR 0005). Read once at startup,
    moved into a Leveling tank WeightPreset, then deleted (ADR 0013)."""

    id: int = Field(default=1, primary_key=True)
    weights: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class WeightPreset(SQLModel, table=True):
    """A stat weight preset saved in the app (ADR 0013).

    shipped=True rows are edits to a preset from the curated files (same key); deleting
    the row resets it. shipped=False rows are the user's own presets.
    """

    key: str = Field(primary_key=True)
    name: str
    shipped: bool = False
    weights: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class ActiveWeightPreset(SQLModel, table=True):
    """Which preset scores everything. One row, id 1; none means Leveling tank."""

    id: int = Field(default=1, primary_key=True)
    key: str


class NotificationDestination(SQLModel, table=True):
    """Where alerts go (ADR 0021): a Discord webhook for now. The URL is a credential
    (anyone holding it can post to the channel): never logged, never returned in full."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    kind: str = "discord_webhook"
    audience: str = "user"  # "user" or "system" (ADR 0020)
    url: str
    alerts: Any = Field(sa_column=Column(JSON, nullable=False))  # list of alert kinds
    enabled: bool = True
    user_id: int | None = None  # set by #16; None while the app has one user
    created_at: datetime = Field(default_factory=utcnow)
    last_sent_at: datetime | None = None
    last_error: str | None = None  # set when a send fails for good, cleared on success


class NotificationOutbox(SQLModel, table=True):
    """Alerts waiting to be sent, or sent; the worker delivers them (ADR 0021).

    One row per destination and dedupe key, so an alert is never queued twice."""

    __table_args__ = (UniqueConstraint("destination_id", "dedupe_key"),)

    id: int | None = Field(default=None, primary_key=True)
    destination_id: int = Field(index=True)
    kind: str
    dedupe_key: str
    payload: Any = Field(sa_column=Column(JSON, nullable=False))  # the Discord message
    created_at: datetime = Field(default_factory=utcnow)
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=utcnow)
    sent_at: datetime | None = None
    failed: bool = False  # gave up: too many attempts, or the webhook is gone
    last_error: str | None = None


class NotificationState(SQLModel, table=True):
    """What alerts compare against: the character as of the last sync (key "digest")."""

    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class ItemChoice(SQLModel, table=True):
    """An item pinned as a target or dismissed from the Upgrades tab (ADR 0012).

    One row per item. The curated YAML files stay the defaults; these add to them.
    """

    item_id: int = Field(primary_key=True)
    choice: str  # "target" or "dismissed"
    name: str  # kept so a dismissed item can be listed after it leaves the pool
    created_at: datetime = Field(default_factory=utcnow)


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


def save_now(session: Session, row: SQLModel) -> None:
    """Write one row and commit straight away.

    SQLite has a single writer, and the API and the worker share one file (ADR 0011).
    Loops that fetch over the network save each result this way, so the write lock is
    held for milliseconds, never across the next request: two refreshes, or a refresh
    and a sync, can then run side by side (ADR 0018).
    """
    session.merge(row)
    session.commit()


MIGRATIONS = Path(__file__).parent / "migrations"


def init_db(engine: Engine) -> None:
    """Bring the schema up to date by running the migrations (#60, ADR 0022).

    A new database gets every table; one from before migrations keeps its tables and
    gains any it's missing (the baseline only creates what doesn't exist), then both
    take every later migration. Safe to run on every start.
    """
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


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
