"""Moving a database: SQLite into Postgres (#44). The target is the suite's own database,
so with TEST_DATABASE_URL set this copies into Postgres for real."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import dbcli
from character_planner.config import Settings
from character_planner.db import (
    Character,
    ProgressHistory,
    Snapshot,
    StoredUsageRules,
    User,
    init_db,
    make_engine,
)
from character_planner.dbcopy import TargetNotEmpty, copy_database

from .test_cli import cli_settings  # noqa: F401  # pyright: ignore[reportUnusedImport]

AT = datetime(2026, 11, 12, 18, 30, tzinfo=UTC)


@pytest.fixture
def source(tmp_path: Path) -> Iterator[Engine]:
    """An instance's SQLite database with a bit of everything in it."""
    engine = make_engine(f"sqlite:///{tmp_path / 'source.db'}")
    init_db(engine)
    with Session(engine) as session:
        user = User(account_id=1001, is_admin=True)
        session.add(user)
        session.flush()
        character = Character(
            user_id=user.id,
            region="us",
            slug="brumboldt-doomlet",
            name="Brumboldt",
            surname="Doomlet",
        )
        session.add(character)
        session.flush()
        session.add(
            Snapshot(
                character_id=character.id,
                source="api",
                kind="profile",
                status=200,
                payload={"level": 19, "name": "Brumboldt", "nested": {"list": [1, 2]}},
                captured_at=AT,
            )
        )
        session.add(ProgressHistory(character_id=character.id, captured_at=AT, level=12))
        session.add(StoredUsageRules(character_id=character.id, rules={"per_slot": 1}))
        session.commit()
    yield engine
    engine.dispose()


def test_everything_is_copied_as_it_was(source: Engine, engine: Engine) -> None:
    copied = copy_database(source, engine)
    assert copied == {
        "user": 1,
        "character": 1,
        "snapshot": 1,
        "progresshistory": 1,
        "storedusagerules": 1,
    }
    with Session(engine) as session:
        (snapshot,) = session.exec(select(Snapshot)).all()
        assert snapshot.payload == {"level": 19, "name": "Brumboldt", "nested": {"list": [1, 2]}}
        assert snapshot.captured_at == AT  # time zones survive
        (character,) = session.exec(select(Character)).all()
        assert (character.slug, character.user_id) == ("brumboldt-doomlet", 1)
        # New rows don't collide with the copied ids (Postgres sequences moved on).
        other = Character(region="eu", slug="someone-else", name="Someone", surname="Else")
        session.add(other)
        session.commit()
        assert other.id is not None and other.id > (character.id or 0)


def test_a_target_with_data_is_refused(source: Engine, engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Character(region="us", slug="already-here", name="Already", surname="Here"))
        session.commit()
    with pytest.raises(TargetNotEmpty, match="character"):
        copy_database(source, engine)


def test_the_command_reads_the_target_from_the_environment(
    source: Engine,
    engine: Engine,
    cli_settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # DATABASE_URL is the source; COPY_TO_DATABASE_URL the target.
    monkeypatch.setattr(
        dbcli,
        "get_settings",
        lambda: cli_settings.model_copy(update={"database_url": str(source.url)}),
    )
    monkeypatch.delenv("COPY_TO_DATABASE_URL", raising=False)
    assert dbcli.main(["copy-to"]) == 2
    monkeypatch.setenv("COPY_TO_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    assert dbcli.main(["copy-to"]) == 0
    out = capsys.readouterr().out
    assert "Copied 5 rows" in out
    assert "  snapshot: 1" in out
    if engine.url.password:  # Postgres: the password never reaches the output
        assert engine.url.password not in out
    assert dbcli.main(["copy-to"]) == 1  # a second copy would duplicate: refused
