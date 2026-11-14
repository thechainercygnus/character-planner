"""Deleting everything stored for the character (#133, ADR 0034), and the privacy notice's
operator contact."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from character_planner import dbcli
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import (
    ClassQuestDone,
    CompanionItem,
    ItemChoice,
    NotificationDestination,
    Snapshot,
    StoredToken,
)
from character_planner.erase import SHARED, erase_character, erased_tables

from .conftest import api_client, tracked
from .test_cli import cli_settings  # noqa: F401  # pyright: ignore[reportUnusedImport]


def store_character(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            Snapshot(
                character_id=tracked(session),
                source="api",
                kind="profile",
                status=200,
                payload={"level": 20},
            )
        )
        session.add(StoredToken(id=1, access_token="tok", expires_at=0, scope="wow.profile"))
        session.add(
            ClassQuestDone(character_id=tracked(session), quest_id="warrior-defensive-stance")
        )
        session.add(
            ItemChoice(
                character_id=tracked(session), item_id=1, choice="dismissed", name="Worn Axe"
            )
        )
        session.add(
            NotificationDestination(
                name="me", url="https://discord.com/api/webhooks/1/x", alerts=[]
            )
        )
        session.add(CompanionItem(item_id=2, found=True, payload={"name": "Shared"}))
        session.commit()


def test_every_shared_table_exists_and_everything_else_is_erased() -> None:
    tables = set(SQLModel.metadata.tables)
    assert tables >= SHARED  # a renamed shared table must be renamed here too
    assert set(erased_tables()) == tables - SHARED
    # The character's own data is never treated as shared.
    assert {"snapshot", "storedtoken", "itemchoice", "notificationdestination"} <= set(
        erased_tables()
    )


def test_erase_removes_the_character_and_keeps_shared_game_data(engine: Engine) -> None:
    store_character(engine)
    with Session(engine) as session:
        assert erase_character(session) == {
            "character": 1,  # seeded again from .env on the next start (ADR 0036)
            "classquestdone": 1,
            "itemchoice": 1,
            "notificationdestination": 1,
            "snapshot": 1,
            "storedtoken": 1,
        }
        assert session.exec(select(Snapshot)).all() == []
        assert session.exec(select(StoredToken)).all() == []
        assert [i.item_id for i in session.exec(select(CompanionItem)).all()] == [2]
        assert erase_character(session) == {}  # nothing left to remove


def test_the_app_erases_on_request_and_shows_no_character_after(
    settings: Settings, engine: Engine
) -> None:
    store_character(engine)
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/character").json()["level"] == 20
        response = client.delete("/api/character")
        assert response.status_code == 200
        assert response.json()["removed"]["snapshot"] == 1
        assert client.get("/api/character").json()["level"] is None


def test_erasing_needs_the_app_header(settings: Settings, engine: Engine) -> None:
    """A page on another site can't erase the data (#124)."""
    store_character(engine)
    with TestClient(create_app(settings, engine)) as client:
        assert client.delete("/api/character").status_code == 403
    with Session(engine) as session:
        assert len(session.exec(select(Snapshot)).all()) == 1


def test_db_erase_needs_yes(cli_settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    assert dbcli.main(["erase"]) == 2
    assert "--yes" in capsys.readouterr().out


def test_db_erase_deletes_the_character(
    cli_settings: Settings,  # noqa: F811
    engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_character(engine)
    assert dbcli.main(["erase", "--yes"]) == 0
    assert capsys.readouterr().out.startswith("Erased 6 rows: ")
    with Session(engine) as session:
        assert session.exec(select(Snapshot)).all() == []


def test_about_shows_the_operators_contact(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/about").json()["operator_contact"] == ""
    run_by = settings.model_copy(update={"operator_contact": "admin@example.org"})
    with api_client(create_app(run_by, engine)) as client:
        assert client.get("/api/about").json()["operator_contact"] == "admin@example.org"


@pytest.mark.parametrize("value", ["two\nlines", "x" * 201, "tab\there"])
def test_the_operator_contact_is_one_short_line(value: str) -> None:
    with pytest.raises(ValueError, match="OPERATOR_CONTACT"):
        Settings(operator_contact=value, _env_file=None)  # pyright: ignore[reportCallIssue]


def test_the_operator_contact_is_trimmed() -> None:
    settings = Settings(operator_contact="  Pat <pat@example.org> ", _env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.operator_contact == "Pat <pat@example.org>"
