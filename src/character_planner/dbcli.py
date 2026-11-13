"""Database commands (#60, ADR 0022).

character-planner-db upgrade   # run the migrations (compose's one-off migrate service)
character-planner-db current   # print the schema version
"""

import argparse
import logging
import sys

from alembic.migration import MigrationContext

from character_planner.config import get_settings
from character_planner.db import init_db, make_engine
from character_planner.logs import configure_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Database schema commands.")
    parser.add_argument("command", choices=["upgrade", "current"])
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings, "worker")
    engine = make_engine(settings.database_url)
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
