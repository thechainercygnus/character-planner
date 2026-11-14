"""Refreshes don't hold SQLite's write lock across network requests (ADR 0018).

The API and the worker share one SQLite file, which allows a single writer. A refresh
that kept its write transaction open while fetching blocked every other writer for
minutes, and they failed with "database is locked".
"""

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.companion import BASE_URL, refresh_companion
from character_planner.config import Settings

from .conftest import TEST_DATABASE_URL
from .test_companion import CAPE, girdle

# SQLite's single writer (ADR 0018) is what this guards; Postgres has no such lock (#44).
pytestmark = pytest.mark.skipif(
    bool(TEST_DATABASE_URL), reason="SQLite's write lock; Postgres has none"
)


def db_path(settings: Settings) -> Path:
    return Path(settings.database_url.removeprefix("sqlite:///"))


@contextmanager
def other_connection(settings: Settings) -> Generator[sqlite3.Connection]:
    """Another process's view of the file, giving up at once if the database is locked.
    Committed, then closed: sqlite3's own `with` only commits, and a connection left to
    the garbage collector closes with a ResourceWarning (warnings are errors, #85)."""
    with closing(sqlite3.connect(db_path(settings), timeout=0)) as connection, connection:
        yield connection


@respx.mock
def test_others_can_write_while_a_refresh_is_fetching(engine: Engine, settings: Settings) -> None:
    seen: dict[str, object] = {}

    def mid_refresh(_request: httpx.Request) -> httpx.Response:
        # Two items are already handled when this third request goes out.
        with other_connection(settings) as other:
            other.execute(
                "INSERT INTO itemchoice (item_id, choice, name, created_at) VALUES (?, ?, ?, ?)",
                (42, "dismissed", "Written mid-refresh", datetime.now(UTC).isoformat()),
            )
            seen["saved_so_far"] = sorted(
                row[0] for row in other.execute("SELECT item_id FROM companionitem")
            )
        return httpx.Response(200, json=CAPE)

    respx.get(f"{BASE_URL}/items/270230").mock(return_value=httpx.Response(200, json=girdle()))
    respx.get(f"{BASE_URL}/items/999").mock(return_value=httpx.Response(404, json={}))
    respx.get(f"{BASE_URL}/items/5193").mock(side_effect=mid_refresh)

    with Session(engine) as session:
        outcome = refresh_companion(session, [270230, 999, 5193])

    assert outcome.fetched == [270230, 5193]
    # What was fetched before is already saved, so an interrupted refresh keeps it.
    assert seen["saved_so_far"] == [999, 270230]
    with other_connection(settings) as other:
        assert other.execute("SELECT name FROM itemchoice WHERE item_id = 42").fetchone() == (
            "Written mid-refresh",
        )
