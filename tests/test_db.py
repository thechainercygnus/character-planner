from pathlib import Path

from sqlalchemy import text

from character_planner.db import SQLITE_BUSY_TIMEOUT_MS, make_engine


def test_sqlite_uses_wal_and_waits_for_locks(tmp_path: Path) -> None:
    # The API and the worker share one SQLite file (ADR 0011).
    engine = make_engine(f"sqlite:///{tmp_path / 'nested' / 'planner.db'}")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == SQLITE_BUSY_TIMEOUT_MS
    assert (tmp_path / "nested").is_dir()
    engine.dispose()
