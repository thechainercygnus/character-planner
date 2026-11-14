"""The command-line tools: character-planner-db (#60) and character-planner-pool (ADR 0006)."""

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import dbcli, pool_cli
from character_planner.companion import BASE_URL
from character_planner.config import Settings
from character_planner.db import Snapshot, init_db, make_engine

from .conftest import tracked
from .test_app import fixture
from .test_dungeons import mock_companion_dungeons
from .test_migrations import head

LOGGING: list[str] = []


@pytest.fixture
def cli_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Both tools read settings themselves: never from a developer's .env here. The db
    tool also configures logging for the whole process, which would leak into later
    tests (the redaction checks in test_notify): record the call instead."""
    monkeypatch.setattr(dbcli, "get_settings", lambda: settings)
    monkeypatch.setattr(pool_cli, "get_settings", lambda: settings)
    LOGGING.clear()
    monkeypatch.setattr(
        dbcli, "configure_logging", lambda _settings, process: LOGGING.append(process)
    )
    return settings


def test_db_current_on_a_new_database_says_none(
    cli_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dbcli.main(["current"]) == 0
    assert capsys.readouterr().out.strip() == "none"
    assert LOGGING == ["worker"]  # its lines go where the worker's do


def test_db_upgrade_runs_the_migrations_and_prints_the_version(
    cli_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dbcli.main(["upgrade"]) == 0
    assert capsys.readouterr().out.strip() == head()
    # And current now reports the same version, without changing anything.
    assert dbcli.main(["current"]) == 0
    assert capsys.readouterr().out.strip() == head()


def test_db_rejects_unknown_commands(cli_settings: Settings) -> None:
    with pytest.raises(SystemExit):
        dbcli.main(["downgrade"])


def store_profile(settings: Settings) -> None:
    engine: Engine = make_engine(settings.database_url)
    init_db(engine)
    with Session(engine) as session:
        session.add(
            Snapshot(
                character_id=tracked(session),
                source="api",
                kind="profile",
                status=200,
                payload=fixture("profile"),
            )
        )
        session.commit()
    engine.dispose()


@respx.mock
def test_pool_refresh_uses_the_synced_level_and_reports(
    cli_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    store_profile(cli_settings)
    mock_companion_dungeons()
    respx.get(url__startswith=f"{BASE_URL}/items/").mock(return_value=httpx.Response(404))

    assert pool_cli.main([]) == 0
    out = capsys.readouterr().out
    # The real profile: level 18, alliance.
    assert "Level 18, faction alliance" in out
    assert "Dungeons: 2 listed, 2 fetched" in out
    assert "Rares: 0 listed" in out
    assert "In window by slot: " in out
    assert "error:" not in out


@respx.mock
def test_pool_refresh_with_a_level_and_errors(
    cli_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(503))
    respx.get(f"{BASE_URL}/rares").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/class-quests").mock(return_value=httpx.Response(200, json={"data": []}))

    # No synced character: the level comes from --level, the faction is unknown.
    assert pool_cli.main(["--level", "30", "--force"]) == 1
    out = capsys.readouterr().out
    assert "Level 30, faction unknown" in out
    assert "  error: Forever Companion dungeon list: HTTP 503" in out
