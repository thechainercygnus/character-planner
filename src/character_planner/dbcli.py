"""Database commands (#60, ADR 0022).

character-planner-db upgrade   # run the migrations (compose's one-off migrate service)
character-planner-db current   # print the schema version
character-planner-db erase --yes  # delete everything stored for the character (#133)
character-planner-db delete-user ACCOUNT_ID --yes  # delete one user and their data (#16)
COPY_TO_DATABASE_URL=... character-planner-db copy-to  # copy DATABASE_URL into another (#44)
"""

import argparse
import logging
import os
import sys

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.config import get_settings
from character_planner.db import init_db, make_engine
from character_planner.dbcopy import TargetNotEmpty, copy_database
from character_planner.erase import erase_character
from character_planner.logs import configure_logging, safe_database_url
from character_planner.users import LastAdmin, delete_user, user_by_account

logger = logging.getLogger(__name__)


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
        "command", choices=["upgrade", "current", "erase", "delete-user", "copy-to"]
    )
    parser.add_argument("account_id", nargs="?", type=int, help="delete-user: the Battle.net id")
    parser.add_argument("--yes", action="store_true", help="confirm a deletion: it can't be undone")
    args = parser.parse_args(argv)
    if args.command == "delete-user" and args.account_id is None:
        print("delete-user needs the user's Battle.net account id")
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
    if args.command == "delete-user":
        try:
            init_db(engine)
            with Session(engine) as session:
                user = user_by_account(session, args.account_id)
                removed = delete_user(session, user.id) if user and user.id else None
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
