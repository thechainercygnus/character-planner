from pathlib import Path

import pytest
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
    )


@pytest.fixture
def engine(settings: Settings) -> Engine:
    engine = make_engine(settings.database_url)
    init_db(engine)
    return engine
