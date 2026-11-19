"""Backups (#240, ADR 0061): what people made in the planner, encrypted, in S3-compatible
storage.

- **Logical, not a database file.** Every table's rows are read through SQLAlchemy and written
  as JSON, gzipped: the same for SQLite and Postgres, a backup restores into either, and the
  image needs no `pg_dump`.
- **Blizzard's data is left out** (Bryce, 2026-11-18): it may be kept at most 30 days (ADR
  0034), so a backup without it can be kept longer. After a restore the next sync fetches it
  again. Left out too: secrets that are renewed anyway (tokens, sessions), and shared caches
  refetched on demand. `EXCLUDED` names every table left out and why; a new table is backed
  up unless it's added there, so nothing is missed by default.
- **Encrypted before it leaves,** with an age public key (Bryce, 2026-11-19): the server can
  encrypt but never decrypt. Restoring needs the private key, kept off the server.
- **Kept:** the newest `BACKUP_KEEP` in the bucket; older ones are deleted after each backup.
- **Restore** (`character-planner-db restore`) goes into an empty database, at the version
  that made the backup: its schema revision must match. Then upgrade as usual.
"""

import gzip
import json
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import boto3
import pyrage
from botocore.config import Config as BotoConfig
from pydantic import BaseModel
from sqlalchemy import Table, delete, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlmodel import Session, SQLModel

from character_planner.config import Settings

if TYPE_CHECKING:  # the stubs are a dev dependency, absent from the image
    from mypy_boto3_s3 import S3Client
from character_planner.db import InstanceSetting, current_revision, init_db, utcnow
from character_planner.dbcopy import SEEDED, move_sequences

logger = logging.getLogger(__name__)

FORMAT: Final = 1
STATUS: Final = "backup_status"  # the last backup, in InstanceSetting
SUFFIX: Final = ".planner-backup.age"
DATETIME: Final = "__planner_datetime__"

# Every table left out of a backup, and why. Snapshots are filtered instead: only those from
# Battle.net ("api") are left out, manual ones are people's.
EXCLUDED: Final[dict[str, str]] = {
    # Blizzard's data: at most 30 days (ADR 0034). The next sync fetches it again.
    "catalogitem": "Blizzard item search",
    "itemicon": "Blizzard item icons",
    "recipedata": "Blizzard recipes",
    "craftingrecipe": "Blizzard recipes",
    "blizzarditem": "Blizzard items",
    "talenttreedata": "Blizzard talent trees",
    "spellicon": "Blizzard spell icons",
    "skilltier": "Blizzard profession recipe lists",
    "notificationstate": "what alerts compare against: Blizzard-derived, rebuilt by a sync",
    # Secrets that are renewed anyway: a restore asks people to sign in again.
    "storedtoken": "the Battle.net token",
    "usertoken": "users' Battle.net tokens",
    "usersession": "sign-in sessions",
    # Shared caches, refetched on demand, and what's in flight.
    "companionitem": "Forever Companion cache",
    "companiondungeon": "Forever Companion cache",
    "companionquest": "Forever Companion cache",
    "companionrare": "Forever Companion cache",
    "companionclassquest": "Forever Companion cache",
    "notificationoutbox": "alerts waiting to be sent",
    "joblease": "jobs running now",
}


def backed_up() -> list[Table]:
    """The tables a backup holds, parents before children."""
    return [t for t in SQLModel.metadata.sorted_tables if t.name not in EXCLUDED]


def _rows(connection: Connection, table: Table) -> list[dict[str, Any]]:
    statement = select(table)
    if table.name == "snapshot":
        statement = statement.where(table.c.source != "api")
    return [dict(row) for row in connection.execute(statement).mappings()]


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {DATETIME: value.isoformat()}
    raise TypeError(f"Can't back up a {type(value).__name__}")


def _decode(value: dict[str, Any]) -> Any:
    if set(value) == {DATETIME}:
        return datetime.fromisoformat(value[DATETIME])
    return value


def dump(engine: Engine, version: str, now: datetime | None = None) -> bytes:
    """Every backed-up table's rows, as gzipped JSON."""
    with engine.connect() as connection:
        tables = {table.name: _rows(connection, table) for table in backed_up()}
    document = {
        "format": FORMAT,
        "app_version": version,
        "revision": current_revision(engine),
        "created_at": (now or utcnow()).isoformat(),
        "tables": tables,
    }
    return gzip.compress(json.dumps(document, default=_encode).encode("utf-8"), mtime=0)


def encrypt(data: bytes, recipient: str) -> bytes:
    return pyrage.encrypt(data, [pyrage.x25519.Recipient.from_str(recipient)])


def decrypt(data: bytes, identity: str) -> bytes:
    return pyrage.decrypt(data, [pyrage.x25519.Identity.from_str(identity.strip())])


class NotEmpty(Exception):
    """Restoring into a database that already holds data."""


class WrongRevision(Exception):
    """A backup from another schema version: restore it with the version that made it."""


def restore(engine: Engine, gzipped: bytes) -> dict[str, int]:
    """Load a decrypted backup into an empty database; returns the rows per table."""
    document = json.loads(gzip.decompress(gzipped), object_hook=_decode)
    if document.get("format") != FORMAT:
        raise ValueError(f"Not a planner backup this version can read: {document.get('format')}")
    init_db(engine)
    revision = current_revision(engine)
    if document["revision"] != revision:
        raise WrongRevision(
            f"This backup is from schema {document['revision']} (planner "
            f"{document['app_version']}); this database is at {revision}. Restore it with "
            f"planner {document['app_version']}, then upgrade."
        )
    tables = {t.name: t for t in SQLModel.metadata.sorted_tables}
    with engine.connect() as connection:
        used = [
            name
            for name, table in tables.items()
            if name not in SEEDED and connection.execute(select(table).limit(1)).first()
        ]
    if used:
        raise NotEmpty(f"Restore into an empty database: this one has data in {', '.join(used)}")
    restored: dict[str, int] = {}
    with engine.begin() as writing:
        for table in SQLModel.metadata.sorted_tables:
            rows = document["tables"].get(table.name)
            if rows is None:
                continue
            if table.name in SEEDED:
                writing.execute(delete(table))
            if rows:
                writing.execute(insert(table), rows)
                restored[table.name] = len(rows)
        move_sequences(writing, SQLModel.metadata.sorted_tables)
    logger.info("Restored %d rows in %d tables", sum(restored.values()), len(restored))
    return restored


# --- storage ------------------------------------------------------------------------------


def s3_client(settings: Settings) -> S3Client:
    # boto3's overloads type the client only partly under strict mode: the stubs' S3Client.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=settings.backup_s3_endpoint or None,
        region_name=settings.backup_s3_region,
        aws_access_key_id=settings.backup_s3_key_id,
        aws_secret_access_key=settings.backup_s3_secret.get_secret_value(),
        config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
    )


def _keys(client: S3Client, settings: Settings) -> list[str]:
    """This instance's backups in the bucket, oldest first (their names sort by time)."""
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=settings.backup_s3_bucket, Prefix=settings.backup_s3_prefix
    ):
        names = (o.get("Key", "") for o in page.get("Contents", []))
        keys.extend(key for key in names if key.endswith(SUFFIX))
    return sorted(keys)


class BackupStatus(BaseModel):
    at: datetime
    ok: bool
    key: str | None = None  # the object written
    size: int | None = None  # bytes, encrypted
    rows: int | None = None
    error: str | None = None
    kept: int | None = None  # backups in the bucket after pruning


def status(session: Session) -> BackupStatus | None:
    row = session.get(InstanceSetting, STATUS)
    return BackupStatus.model_validate(row.value) if row is not None else None


def _save(session: Session, result: BackupStatus) -> None:
    row = session.get(InstanceSetting, STATUS) or InstanceSetting(key=STATUS, value={})
    row.value = result.model_dump(mode="json")
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def due(session: Session, settings: Settings, now: datetime | None = None) -> bool:
    """A backup is due when the last good one is older than BACKUP_EVERY_HOURS: the worker
    restarting doesn't make one."""
    last = status(session)
    if last is None or not last.ok:
        return True
    at = last.at if last.at.tzinfo else last.at.replace(tzinfo=UTC)
    return (now or utcnow()) - at >= timedelta(hours=settings.backup_every_hours)


def run_backup(
    session: Session,
    settings: Settings,
    version: str,
    *,
    client: Callable[[Settings], S3Client] = s3_client,
    now: datetime | None = None,
) -> BackupStatus:
    """Dump, encrypt, upload, prune, and record the outcome. Raises on failure, after
    recording it, so the worker's failed-job alert reaches the admin (ADR 0045)."""
    when = now or utcnow()
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    try:
        data = dump(engine, version, when)
        rows = sum(len(r) for r in json.loads(gzip.decompress(data))["tables"].values())
        sealed = encrypt(data, settings.backup_age_recipient)
        key = f"{settings.backup_s3_prefix}{when:%Y%m%dT%H%M%SZ}-{version}{SUFFIX}"
        s3 = client(settings)
        s3.put_object(Bucket=settings.backup_s3_bucket, Key=key, Body=sealed)
        keys = _keys(s3, settings)
        old = keys[: max(0, len(keys) - settings.backup_keep)]
        _delete(s3, settings, old)
        result = BackupStatus(
            at=when, ok=True, key=key, size=len(sealed), rows=rows, kept=len(keys) - len(old)
        )
    except Exception as error:
        _save(session, BackupStatus(at=when, ok=False, error=f"{type(error).__name__}: {error}"))
        raise
    _save(session, result)
    logger.info("Backup: %d rows, %d bytes, %d kept", rows, len(sealed), result.kept or 0)
    return result


def _delete(client: S3Client, settings: Settings, keys: Iterable[str]) -> None:
    for key in keys:
        client.delete_object(Bucket=settings.backup_s3_bucket, Key=key)


def app_version() -> str:
    """The running planner's version, as backups name it."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("character-planner")
    except PackageNotFoundError:
        return "unknown"
