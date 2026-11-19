"""Database commands (#60, ADR 0022).

character-planner-db upgrade   # run the migrations (compose's one-off migrate service)
character-planner-db current   # print the schema version
character-planner-db erase --yes  # delete everything stored for the character (#133)
character-planner-db delete-user ACCOUNT_ID --yes  # delete one user and their data (#16)
COPY_TO_DATABASE_URL=... character-planner-db copy-to  # copy DATABASE_URL into another (#44)
character-planner-db backup  # back up now, as the worker does (#240)
character-planner-db restore --file BACKUP [--identity KEY] --yes  # into an empty database
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import backup
from character_planner.admin_log import record
from character_planner.config import Settings, get_settings
from character_planner.db import init_db, make_engine
from character_planner.dbcopy import TargetNotEmpty, copy_database
from character_planner.erase import erase_character
from character_planner.logs import configure_logging, safe_database_url
from character_planner.users import LastAdmin, delete_user, user_by_account

logger = logging.getLogger(__name__)


def backup_now(engine: Engine, settings: Settings) -> int:
    """Back up now (#240), as the worker's job does, whatever the schedule."""
    if not settings.backups:
        print(
            "Backups aren't set up: set BACKUP_S3_* and BACKUP_AGE_RECIPIENT (docs/self-hosting.md)"
        )
        return 2
    try:
        init_db(engine)
        with Session(engine) as session:
            result = backup.run_backup(session, settings, backup.app_version())
    except Exception as error:
        print(f"Backup failed: {type(error).__name__}: {error}")
        return 1
    finally:
        engine.dispose()
    print(f"Backed up {result.rows} rows to {result.key} ({result.size} bytes); {result.kept} kept")
    return 0


def restore_file(engine: Engine, path: str, identity: str | None) -> int:
    """Load a backup into DATABASE_URL, which must be empty (#240). An encrypted one needs
    --identity; one decrypted with age on another machine needs nothing."""
    data = Path(path).read_bytes()
    try:
        if identity is not None:
            data = backup.decrypt(data, Path(identity).read_text(encoding="utf-8"))
        restored = backup.restore(engine, data)
    except (backup.NotEmpty, backup.WrongRevision, ValueError) as error:
        print(error)
        return 1
    finally:
        engine.dispose()
    print(f"Restored {sum(restored.values())} rows in {len(restored)} tables")
    return 0


def copy_to(source: Engine) -> int:
    """Copy this database (DATABASE_URL) into the one COPY_TO_DATABASE_URL names (#44).
    The target comes from the environment, not the command line, so its password stays
    out of shell history and process lists."""
    url = os.environ.get("COPY_TO_DATABASE_URL", "")
    if not url:
        print(
            "Set COPY_TO_DATABASE_URL to the database to copy into, e.g. postgresql+psycopg://..."
        )
        source.dispose()
        return 2
    target = make_engine(url)
    try:
        copied = copy_database(source, target)
    except TargetNotEmpty as error:
        print(error)
        return 1
    finally:
        target.dispose()
        source.dispose()
    print(
        f"Copied {sum(copied.values())} rows from {safe_database_url(str(source.url))} "
        f"into {safe_database_url(url)}"
    )
    for table, count in copied.items():
        print(f"  {table}: {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Database schema commands.")
    parser.add_argument(
        "command",
        choices=["upgrade", "current", "erase", "delete-user", "copy-to", "backup", "restore"],
    )
    parser.add_argument("account_id", nargs="?", type=int, help="delete-user: the Battle.net id")
    parser.add_argument("--yes", action="store_true", help="confirm a deletion: it can't be undone")
    parser.add_argument("--file", help="restore: the backup, as downloaded or decrypted (#240)")
    parser.add_argument(
        "--identity", help="restore: an age identity file, to decrypt here instead of with age"
    )
    args = parser.parse_args(argv)
    if args.command == "delete-user" and args.account_id is None:
        print("delete-user needs the user's Battle.net account id")
        return 2
    if args.command == "restore" and not args.file:
        print("restore needs --file: the backup, encrypted (.age, with --identity) or decrypted")
        return 2
    if args.command == "restore" and not args.yes:
        print("restore loads a backup into DATABASE_URL, which must be empty; add --yes")
        return 2
    if args.command in ("erase", "delete-user") and not args.yes:
        what = "everything stored" if args.command == "erase" else "the user and their data"
        print(f"{args.command} deletes {what}; add --yes to confirm")
        return 2
    settings = get_settings()
    configure_logging(settings, "worker")
    engine = make_engine(settings.database_url)
    if args.command == "copy-to":
        return copy_to(engine)
    if args.command == "backup":
        return backup_now(engine, settings)
    if args.command == "restore":
        return restore_file(engine, args.file, args.identity)
    if args.command == "delete-user":
        try:
            init_db(engine)
            with Session(engine) as session:
                user = user_by_account(session, args.account_id)
                removed = delete_user(session, user.id) if user and user.id else None
                if removed is not None:
                    # The record a data request was handled (#238, ADR 0056): no actor here.
                    rows = f"{sum(removed.values())} rows, from the command line"
                    record(session, "user.delete", actor=None, target=args.account_id, detail=rows)
        except LastAdmin as error:
            print(error)
            return 1
        finally:
            engine.dispose()
        if removed is None:
            print(f"No user with Battle.net account id {args.account_id}")
            return 1
        print(f"Deleted the user and {sum(removed.values()) - 1} rows of their data")
        return 0
    if args.command == "erase":
        try:
            init_db(engine)
            with Session(engine) as session:
                removed = erase_character(session)
        finally:
            engine.dispose()
        logger.info("Erased the character's data: %d rows", sum(removed.values()))
        tables = ", ".join(f"{table} {count}" for table, count in removed.items())
        print(f"Erased {sum(removed.values())} rows: {tables or 'nothing stored'}")
        return 0
    try:
        if args.command == "upgrade":
            init_db(engine)
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    logger.info("Database schema version: %s", current or "none")
    print(current or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
