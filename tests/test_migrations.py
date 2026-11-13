"""Schema migrations (#60, ADR 0022): every kind of database ends at the same schema."""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from character_planner.db import (
    MIGRATIONS,
    Snapshot,
    StoredGearTargets,
    init_db,
    make_engine,
)

NOTIFICATION_TABLES = {"notificationdestination", "notificationoutbox", "notificationstate"}


# Tables added by migrations after the baseline: databases made before #60 never had
# them. Add each new table here when its migration is added.
AFTER_BASELINE = {"joblease", "talenttreedata", "spellicon"}  # 0002, 0003


def create_like_before_migrations(engine: Engine) -> None:
    """Make a database the way every one was made before #60: create_all, at the
    baseline's tables."""
    tables = [t for name, t in SQLModel.metadata.tables.items() if name not in AFTER_BASELINE]
    SQLModel.metadata.create_all(engine, tables=tables)


def engine_at(tmp_path: Path, name: str = "planner.db") -> Engine:
    return make_engine(f"sqlite:///{tmp_path / name}")


def head() -> str:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"migrations have split into {heads}: merge them"
    return heads[0]


def version(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def differences(engine: Engine) -> list[object]:
    """What the models have that the database doesn't, or the other way round."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, SQLModel.metadata))


def test_a_new_database_gets_every_table(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    assert set(SQLModel.metadata.tables) <= tables
    assert version(engine) == head()


def test_the_migrations_match_the_models(tmp_path: Path) -> None:
    """Fails when a table in db.py changes without a migration: add one with
    `uv run alembic revision --autogenerate -m "..."` (see migrations/__init__.py)."""
    engine = engine_at(tmp_path)
    init_db(engine)
    assert differences(engine) == []


def test_a_database_from_before_migrations_keeps_its_data(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    create_like_before_migrations(engine)
    with Session(engine) as session:
        session.add(Snapshot(source="api", kind="profile", status=200, payload={"level": 19}))
        session.add(StoredGearTargets(id=1, targets={"targets": []}))
        session.commit()

    init_db(engine)

    assert version(engine) == head()
    assert differences(engine) == []
    with Session(engine) as session:
        (snapshot,) = session.exec(select(Snapshot)).all()
        assert snapshot.payload == {"level": 19}
        assert session.get(StoredGearTargets, 1) is not None


def test_an_older_database_gains_the_tables_it_is_missing(tmp_path: Path) -> None:
    """A copy from before #12 (no notification tables) upgrading straight to now."""
    engine = engine_at(tmp_path)
    create_like_before_migrations(engine)
    with engine.begin() as connection:
        for table in NOTIFICATION_TABLES:
            connection.execute(text(f"DROP TABLE {table}"))
        connection.execute(
            text(
                "INSERT INTO snapshot (source, kind, status, payload, captured_at) "
                "VALUES ('api', 'profile', 200, '{}', '2026-11-01 00:00:00')"
            )
        )

    init_db(engine)

    assert set(inspect(engine).get_table_names()) >= NOTIFICATION_TABLES
    assert differences(engine) == []
    with Session(engine) as session:
        assert len(session.exec(select(Snapshot)).all()) == 1


def test_running_again_changes_nothing(tmp_path: Path) -> None:
    engine = engine_at(tmp_path)
    init_db(engine)
    init_db(engine)
    assert version(engine) == head()


@pytest.mark.parametrize("name", ["a.db", "nested/dir/b.db"])
def test_a_database_in_a_new_folder_is_created(tmp_path: Path, name: str) -> None:
    engine = engine_at(tmp_path, name)
    init_db(engine)
    assert (tmp_path / name).exists()
