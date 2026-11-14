"""Schema migrations (#60, ADR 0022): every kind of database ends at the same schema."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from character_planner.characters import current_character
from character_planner.config import Settings
from character_planner.db import (
    MIGRATIONS,
    ItemChoice,
    ProgressHistory,
    Snapshot,
    StoredGearTargets,
    StoredUsageRules,
    init_db,
    make_engine,
)

NOTIFICATION_TABLES = {"notificationdestination", "notificationoutbox", "notificationstate"}


def create_like_before_migrations(engine: Engine) -> None:
    """Make a database the way every one was made before #60: the baseline's tables as
    they were then, and no version table. Built from the baseline migration itself, so
    later column changes to those tables (#14's character_id) don't leak in."""
    from alembic import command

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.execute(text("DROP TABLE alembic_version"))


ENGINES: list[Engine] = []


@pytest.fixture(autouse=True)
def dispose_engines() -> Iterator[None]:
    """Close every engine a test made: see the engine fixture in conftest.py."""
    yield
    while ENGINES:
        ENGINES.pop().dispose()


def engine_at(tmp_path: Path, name: str = "planner.db") -> Engine:
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    ENGINES.append(engine)
    return engine


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
    with engine.begin() as connection:  # the old columns: no character_id yet
        connection.execute(
            text(
                "INSERT INTO snapshot (source, kind, status, payload, captured_at) "
                """VALUES ('api', 'profile', 200, '{"level": 19}', '2026-11-01 00:00:00')"""
            )
        )
        connection.execute(
            text(
                "INSERT INTO storedgeartargets (id, targets, updated_at) "
                """VALUES (1, '{"targets": []}', '2026-11-01 00:00:00')"""
            )
        )

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


def test_a_database_from_0_3_keeps_its_data_and_settings(
    tmp_path: Path, settings: Settings
) -> None:
    """#14: an instance upgrading from one character to records keeps everything, and the
    first start gives it to the character .env names (ADR 0036)."""
    from alembic import command

    engine = engine_at(tmp_path)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0009")
        connection.execute(
            text(
                "INSERT INTO snapshot (source, kind, status, payload, captured_at) VALUES "
                """('api', 'profile', 200, '{"level": 19}', '2026-11-12 00:00:00')"""
            )
        )
        connection.execute(
            text(
                "INSERT INTO progresshistory (captured_at, level, item_level) "
                "VALUES ('2026-10-01 00:00:00', 12, 8.0)"
            )
        )
        # Settings edited in 0.3: one set for the instance.
        connection.execute(
            text(
                "INSERT INTO storedusagerules (id, rules, updated_at) "
                """VALUES (1, '{"per_slot": 1}', '2026-11-01 00:00:00')"""
            )
        )
        connection.execute(
            text(
                "INSERT INTO itemchoice (item_id, choice, name, created_at) "
                "VALUES (7, 'dismissed', 'Worn Axe', '2026-11-01 00:00:00')"
            )
        )

    init_db(engine)
    assert differences(engine) == []
    with Session(engine) as session:
        character = current_character(session, settings)
        assert character is not None
        (snapshot,) = session.exec(select(Snapshot)).all()
        (history,) = session.exec(select(ProgressHistory)).all()
        assert (snapshot.character_id, snapshot.payload) == (character.id, {"level": 19})
        assert (history.character_id, history.level) == (character.id, 12)
        (rules,) = session.exec(select(StoredUsageRules)).all()
        (choice,) = session.exec(select(ItemChoice)).all()
        assert (rules.character_id, rules.rules) == (character.id, {"per_slot": 1})
        assert (choice.character_id, choice.item_id) == (character.id, 7)
