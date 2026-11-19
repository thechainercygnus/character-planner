"""Data requests from the admin area (#238, ADR 0056): delete an account, export it, and the
log that records both. Two users throughout, the admin and a guildmate, each with their
own character, data and alert webhook: one user's request never reaches the other."""

import io
import json
import zipfile
from datetime import timedelta

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import admin_log
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import AdminAction, Character, Snapshot, User, UserToken, utcnow

from .test_notify import HOOK_TOKEN, OTHER
from .test_own_webhooks import add_hook
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in, users_on  # noqa: F401


def open_app(settings: Settings, engine: Engine) -> FastAPI:
    return create_app(settings.model_copy(update={"planner_signups": True}), engine)


def user_id(engine: Engine, account_id: int) -> int:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.account_id == account_id)).one()
        assert user.id is not None
        return user.id


def give_character(engine: Engine, account_id: int) -> None:
    """The guildmate's own character, with a snapshot: theirs to export or delete."""
    with Session(engine) as session:
        character = Character(
            user_id=user_id(engine, account_id), region="eu", slug="lilalx", name="Lilalx"
        )
        session.add(character)
        session.commit()
        session.add(
            Snapshot(
                character_id=character.id,
                source="api",
                kind="profile",
                status=200,
                payload={"name": "Lilalx", "level": 12},
            )
        )
        session.commit()


def two_users(app: FastAPI, engine: Engine, admin: TestClient, guildmate: TestClient) -> None:
    sign_in(admin, ADMIN)
    sign_in(guildmate, GUILDMATE)
    give_character(engine, GUILDMATE)
    add_hook(guildmate, OTHER)


def log(engine: Engine) -> list[tuple[int | None, str, int | None, str | None]]:
    with Session(engine) as session:
        return [
            (e.actor_account_id, e.action, e.target_account_id, e.detail)
            for e in admin_log.recent(session)
        ]


@respx.mock
def test_an_export_holds_one_accounts_data_and_no_secrets(
    users_on: Settings,  # noqa: F811
    engine: Engine,
) -> None:
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        two_users(app, engine, admin, guildmate)
        response = admin.get(f"/api/admin/users/{user_id(engine, GUILDMATE)}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f'filename="character-planner-{GUILDMATE}-' in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert names == {
        "README.txt",
        "account.json",
        "characters/eu-lilalx/character.json",
        "characters/eu-lilalx/snapshot.json",
        "alerts.json",
    }  # nothing of the admin's: their Brumboldt isn't here
    account = json.loads(archive.read("account.json"))
    assert account["account_id"] == GUILDMATE and account["role"] == "user"
    (snapshot,) = json.loads(archive.read("characters/eu-lilalx/snapshot.json"))
    assert snapshot["payload"] == {"name": "Lilalx", "level": 12}
    (hook,) = json.loads(archive.read("alerts.json"))
    assert hook["url"] == "…/webhooks/987654321098765432/••••"  # masked: a credential
    everything = b"".join(archive.read(name) for name in names).decode()
    assert HOOK_TOKEN not in everything
    with Session(engine) as session:
        token = session.get(UserToken, user_id(engine, GUILDMATE))
        assert token is not None and token.access_token not in everything
    assert "Not included: sign-in sessions" in archive.read("README.txt").decode()
    assert log(engine)[0] == (ADMIN, "user.export", GUILDMATE, None)


@respx.mock
def test_deleting_an_account_needs_its_id_and_spares_everyone_else(
    users_on: Settings,  # noqa: F811
    engine: Engine,
) -> None:
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        two_users(app, engine, admin, guildmate)
        theirs = user_id(engine, GUILDMATE)
        assert admin.delete(f"/api/admin/users/{theirs}").status_code == 409  # no confirmation
        wrong = admin.delete(f"/api/admin/users/{theirs}", params={"confirm": ADMIN})
        assert wrong.status_code == 409 and str(GUILDMATE) in wrong.json()["detail"]
        assert admin.delete("/api/admin/users/999", params={"confirm": 1}).status_code == 404

        done = admin.delete(f"/api/admin/users/{theirs}", params={"confirm": GUILDMATE})
        assert done.status_code == 200
        removed = done.json()["removed"]
        assert removed["user"] == 1 and removed["character"] == 1 and removed["snapshot"] == 1
        assert removed["notificationdestination"] == 1 and removed["usertoken"] == 1

        assert guildmate.get("/api/characters").status_code == 401  # their session went too
        assert admin.get("/api/character").status_code == 200  # the admin's is untouched
        accounts = admin.get("/api/admin/accounts").json()["accounts"]
        assert [a["account_id"] for a in accounts] == [ADMIN]

        # The admin goes last (ADR 0037).
        mine = user_id(engine, ADMIN)
        sign_in(guildmate, GUILDMATE)  # back, as a new account
        last = admin.delete(f"/api/admin/users/{mine}", params={"confirm": ADMIN})
        assert last.status_code == 409

    with Session(engine) as session:
        characters = session.exec(select(Character)).all()
        assert [c.slug for c in characters] == ["brumboldt-doomlet"]
    # The record outlives the account it names.
    assert (ADMIN, "user.delete", GUILDMATE) in [entry[:3] for entry in log(engine)]


@respx.mock
def test_data_requests_are_the_admins_alone(users_on: Settings, engine: Engine) -> None:  # noqa: F811
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as superuser:
        two_users(app, engine, admin, superuser)
        theirs, mine = user_id(engine, GUILDMATE), user_id(engine, ADMIN)
        promote = admin.put(f"/api/admin/users/{theirs}/role", json={"role": "superuser"})
        assert promote.is_success
        # A superuser sees the accounts, but deletes, exports and reads the log not at all.
        assert superuser.get("/api/admin/accounts").status_code == 200
        assert superuser.get(f"/api/admin/users/{mine}/export").status_code == 403
        assert (
            superuser.delete(f"/api/admin/users/{mine}", params={"confirm": ADMIN}).status_code
            == 403
        )
        assert superuser.get("/api/admin/log").status_code == 403


@respx.mock
def test_the_log_records_who_did_what_to_whom(users_on: Settings, engine: Engine) -> None:  # noqa: F811
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        two_users(app, engine, admin, guildmate)
        theirs = user_id(engine, GUILDMATE)
        admin.put(f"/api/admin/users/{theirs}/role", json={"role": "superuser"})
        guildmate.put("/api/enchants/corrections/per-slot", json={"per_slot": 2})
        admin.put(f"/api/admin/users/{theirs}/role", json={"role": "user"})
        entries = admin.get("/api/admin/log").json()

    assert [
        (e["actor_account_id"], e["action"], e["target_account_id"], e["detail"]) for e in entries
    ] == [
        (ADMIN, "role.change", GUILDMATE, "superuser -> user"),
        (GUILDMATE, "enchants.correct", None, "per slot: 2"),
        (ADMIN, "role.change", GUILDMATE, "user -> superuser"),
    ]
    fields = {"id", "at", "actor_account_id", "action", "target_account_id", "detail"}
    assert set(entries[0]) == fields


def test_without_users_nothing_is_logged_and_there_is_no_admin_area(
    settings: Settings, engine: Engine
) -> None:
    with TestClient(create_app(settings, engine)) as client:
        headers = {"X-Requested-With": "character-planner"}
        assert client.put(
            "/api/enchants/corrections/per-slot", json={"per_slot": 2}, headers=headers
        ).is_success
        assert client.get("/api/admin/log").status_code == 404
        assert client.get("/api/admin/users/1/export").status_code == 404
        assert (
            client.delete("/api/admin/users/1", params={"confirm": 1}, headers=headers).status_code
            == 404
        )
    assert log(engine) == []


def test_entries_older_than_a_year_are_pruned(engine: Engine) -> None:
    with Session(engine) as session:
        admin_log.record(session, "user.export", actor=1, target=2)
        session.add(
            AdminAction(action="user.delete", actor_account_id=1, at=utcnow() - timedelta(days=366))
        )
        session.commit()
        assert admin_log.prune(session) == 1
        assert [e.action for e in admin_log.recent(session)] == ["user.export"]


def test_the_export_needs_a_user(engine: Engine) -> None:
    from character_planner.export import export_user

    with Session(engine) as session, pytest.raises(LookupError):
        export_user(session, 999)
