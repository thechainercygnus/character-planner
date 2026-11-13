"""Alembic's environment: run migrations against the app's database (ADR 0022).

The app runs them itself at startup through db.init_db(), which hands over its own
connection. The alembic command line (alembic.ini at the repo root) uses DATABASE_URL
from the settings instead.
"""

from alembic import context
from sqlmodel import SQLModel

from character_planner import db
from character_planner.config import get_settings

target_metadata = SQLModel.metadata


def _configure(connection: object | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        url=url,
        target_metadata=target_metadata,
        # SQLite can't alter most column properties in place: batch mode copies the table.
        render_as_batch=True,
        compare_type=True,
    )


def run_offline() -> None:
    _configure(url=get_settings().database_url)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = db.make_engine(get_settings().database_url)
    with engine.connect() as own:
        _configure(connection=own)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
