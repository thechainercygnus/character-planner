from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from character_planner.config import Settings
from character_planner.db import init_db, make_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # _env_file=None: tests must never read a developer's real .env
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        bnet_client_id="test-client",
        bnet_client_secret=SecretStr("test-secret"),
        bnet_region="us",
        bnet_redirect_uri="http://localhost:8000/auth/callback",
        character_name="Brumboldt",
        character_surname="Doomlet",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        curated_dir=REPO_ROOT / "data" / "curated",
        post_login_redirect="http://localhost:5173/",
        frontend_dist=tmp_path / "no-frontend-build",
        companion_request_pause=0,
        planner_hosts="testserver",  # the test client's host name
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    # Disposed after the test: SQLite connections left to the garbage collector close
    # with a ResourceWarning, which fails the run (warnings are errors, #85).
    engine = make_engine(settings.database_url)
    init_db(engine)
    yield engine
    engine.dispose()


# The header the web app sends (#124): API tests send it too, as the browser would.
APP_HEADERS = {"X-Requested-With": "character-planner"}


def api_client(app: Any) -> TestClient:
    """A test client that sends the web app's header on every request."""
    return TestClient(app, headers=APP_HEADERS)
