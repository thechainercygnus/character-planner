"""Copy one database into another (#44): an instance moving from SQLite to Postgres keeps
its snapshots, history, characters, users and settings.

Both are brought to the newest schema first, so the tables match. The target must be
empty. Tables are copied parents before children, so foreign keys hold, and Postgres's id
sequences are moved past the copied ids so new rows don't collide with them.
"""

import logging
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from character_planner.db import init_db

logger = logging.getLogger(__name__)

BATCH = 500


class TargetNotEmpty(Exception):
    """The database to copy into already holds data."""


def copy_database(source: Engine, target: Engine) -> dict[str, int]:
    """Copy every table from source into target; returns the rows copied per table."""
    init_db(source)
    init_db(target)
    tables = SQLModel.metadata.sorted_tables
    with target.connect() as connection:
        used = [
            t.name
            for t in tables
            if connection.execute(select(func.count()).select_from(t)).scalar()
        ]
    if used:
        raise TargetNotEmpty(f"The target already has data in: {', '.join(used)}")
    copied: dict[str, int] = {}
    with source.connect() as reading, target.begin() as writing:
        for table in tables:
            rows: list[dict[str, Any]] = [
                dict(row) for row in reading.execute(select(table)).mappings()
            ]
            for start in range(0, len(rows), BATCH):
                writing.execute(insert(table), rows[start : start + BATCH])
            if rows:
                copied[table.name] = len(rows)
        if target.dialect.name == "postgresql":
            for table in tables:
                id_column = table.columns.get("id")
                if id_column is None or not id_column.autoincrement or not id_column.primary_key:
                    continue
                highest = writing.execute(select(func.max(id_column))).scalar()
                sequence = func.pg_get_serial_sequence(f'"{table.name}"', "id")
                writing.execute(select(func.setval(sequence, highest or 1, highest is not None)))
    logger.info("Copied %d rows in %d tables", sum(copied.values()), len(copied))
    return copied
