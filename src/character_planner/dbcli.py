"""Database commands (#60, ADR 0022).

character-planner-db upgrade   # run the migrations (compose's one-off migrate service)
character-planner-db current   # print the schema version
character-planner-db erase --yes  # delete everything stored for the character (#133)
"""

import argparse
import logging
import sys

from alembic.migration import MigrationContext
from sqlmodel import Session

from character_planner.config import get_settings
from character_planner.db import init_db, make_engine
from character_planner.erase import erase_character
from character_planner.logs import configure_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Database schema commands.")
    parser.add_argument("command", choices=["upgrade", "current", "erase"])
    parser.add_argument("--yes", action="store_true", help="confirm erase: it can't be undone")
    args = parser.parse_args(argv)
    if args.command == "erase" and not args.yes:
        print("erase deletes everything stored for the character; add --yes to confirm")
        return 2
    settings = get_settings()
    configure_logging(settings, "worker")
    engine = make_engine(settings.database_url)
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
