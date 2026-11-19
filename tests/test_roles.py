"""Roles and permissions (#237, ADR 0055): the admin, superusers and users, with what each
may do kept as data and checked by name on each route. Three users throughout: the admin
(the first sign-in), a superuser and a user."""

from pathlib import Path

import respx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import Role, User, init_db
from character_planner.roles import DEFAULTS, PERMISSIONS, permissions_of

from .test_migrations import MIGRATIONS, engine_at
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in, users_on  # noqa: F401

THIRD = 3003  # a third Battle.net account


def open_app(settings: Settings, engine: Engine) -> FastAPI:
    return create_app(settings.model_copy(update={"planner_signups": True}), engine)


def user_id(engine: Engine, account_id: int) -> int:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.account_id == account_id)).one()
        assert user.id is not None
        return user.id


def test_the_admin_may_do_everything_and_users_nothing_instance_wide(engine: Engine) -> None:
    with Session(engine) as session:
        assert permissions_of(session, "admin") == frozenset(PERMISSIONS)
        assert permissions_of(session, "superuser") == frozenset(DEFAULTS["superuser"])
        assert permissions_of(session, "user") == frozenset()
        assert permissions_of(session, "nobody") == frozenset()


def test_permissions_are_data(engine: Engine) -> None:
    """Changing what a role may do is a change to its row, not to code."""
    with Session(engine) as session:
        superuser = session.get(Role, "superuser")
        assert superuser is not None
        superuser.permissions = [*superuser.permissions, "discord.signup", "not.a.permission"]
        session.add(superuser)
        admin = session.get(Role, "admin")
        assert admin is not None
        admin.permissions = []  # the admin keeps everything whatever its row says
        session.add(admin)
        session.commit()
        assert "discord.signup" in permissions_of(session, "superuser")
        assert "not.a.permission" not in permissions_of(session, "superuser")
        assert permissions_of(session, "admin") == frozenset(PERMISSIONS)


@respx.mock
def test_the_admin_lists_accounts_and_makes_a_superuser(users_on: Settings, engine: Engine) -> None:  # noqa: F811
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate, browser(app) as third:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        sign_in(third, THIRD)
        view = admin.get("/api/admin/accounts").json()
        accounts = {a["account_id"]: a for a in view["accounts"]}
        assert [a["role"] for a in view["accounts"]] == ["admin", "user", "user"]
        assert [c["name"] for c in accounts[ADMIN]["characters"]] == ["Brumboldt Doomlet"]
        assert accounts[GUILDMATE]["characters"] == []
        assert set(accounts[ADMIN]) == {
            "user_id",
            "account_id",
            "role",
            "created_at",
            "last_sign_in_at",
            "characters",
        }  # what's stored, and nothing more
        assert [r["name"] for r in view["roles"]] == ["admin", "superuser", "user"]
        assert view["permissions"] == PERMISSIONS

        # A user sees none of it.
        assert guildmate.get("/api/admin/accounts").status_code == 403
        assert guildmate.get("/api/me").json()["permissions"] == []

        made = admin.put(
            f"/api/admin/users/{accounts[GUILDMATE]['user_id']}/role", json={"role": "superuser"}
        )
        assert made.status_code == 200 and made.json()["role"] == "superuser"
        me = guildmate.get("/api/me").json()
        assert (me["role"], me["admin"]) == ("superuser", False)
        assert me["permissions"] == sorted(DEFAULTS["superuser"])


@respx.mock
def test_each_permission_is_enforced_on_its_routes(users_on: Settings, engine: Engine) -> None:  # noqa: F811
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as superuser, browser(app) as user:
        sign_in(admin, ADMIN)
        sign_in(superuser, GUILDMATE)
        sign_in(user, THIRD)
        guildmate = user_id(engine, GUILDMATE)
        third = user_id(engine, THIRD)
        assert admin.put(
            f"/api/admin/users/{guildmate}/role", json={"role": "superuser"}
        ).is_success

        # accounts.view: the superuser's too.
        assert superuser.get("/api/admin/accounts").status_code == 200
        # roles.manage: the admin's alone.
        change = superuser.put(f"/api/admin/users/{third}/role", json={"role": "superuser"})
        assert change.status_code == 403
        # enchants.correct: the superuser's, not a user's.
        per_slot = {"per_slot": 2}
        assert superuser.put("/api/enchants/corrections/per-slot", json=per_slot).status_code == 200
        assert user.put("/api/enchants/corrections/per-slot", json=per_slot).status_code == 403
        # discord.signup: instance-wide, the admin's alone.
        assert superuser.post("/api/discord/signup-message").status_code == 403

        # Back to a user: the permissions go with the role.
        assert admin.put(f"/api/admin/users/{guildmate}/role", json={"role": "user"}).is_success
        assert superuser.get("/api/admin/accounts").status_code == 403


@respx.mock
def test_the_admins_role_is_never_granted_or_taken(users_on: Settings, engine: Engine) -> None:  # noqa: F811
    mock_battle_net()
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        mine, theirs = user_id(engine, ADMIN), user_id(engine, GUILDMATE)
        demote = admin.put(f"/api/admin/users/{mine}/role", json={"role": "user"})
        assert demote.status_code == 409
        assert "admin's role" in demote.json()["detail"]
        promote = admin.put(f"/api/admin/users/{theirs}/role", json={"role": "admin"})
        assert promote.status_code == 422
        unknown = admin.put("/api/admin/users/999/role", json={"role": "user"})
        assert unknown.status_code == 404
        assert admin.get("/api/me").json()["role"] == "admin"


def test_without_users_there_are_no_accounts(settings: Settings, engine: Engine) -> None:
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/api/admin/accounts").status_code == 404
        response = client.put(
            "/api/admin/users/1/role",
            json={"role": "user"},
            headers={"X-Requested-With": "character-planner"},
        )
        assert response.status_code == 404


def test_the_migration_keeps_the_admin(tmp_path: Path) -> None:
    """0019's data step: is_admin becomes the admin role, everyone else a user."""
    engine = engine_at(tmp_path)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0018")
        for uid, account, admin in ((7, 1001, True), (8, 2002, False)):
            connection.execute(
                text(
                    'INSERT INTO "user" (id, account_id, is_admin, created_at, last_sign_in_at) '
                    "VALUES (:id, :account, :admin, '2026-11-14 00:00:00', '2026-11-14 00:00:00')"
                ),
                {"id": uid, "account": account, "admin": admin},
            )
    init_db(engine)
    with Session(engine) as session:
        roles = {u.account_id: u.role for u in session.exec(select(User))}
        assert roles == {1001: "admin", 2002: "user"}
        stored = {r.name: r.permissions for r in session.exec(select(Role))}
        assert stored == DEFAULTS
