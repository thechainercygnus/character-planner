"""Users, sessions and per-user isolation (#16, ADR 0037)."""

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import Character, User, UserSession, utcnow
from character_planner.users import COOKIE

from .conftest import api_client
from .test_cli import cli_settings  # noqa: F401  # pyright: ignore[reportUnusedImport]

ACCOUNT_URL = "https://us.api.blizzard.com/profile/user/wow"
ADMIN, GUILDMATE = 1001, 2002  # Battle.net account ids


@pytest.fixture
def users_on(settings: Settings) -> Settings:
    return settings.model_copy(update={"planner_users": True})


def mock_battle_net() -> None:
    """Each sign-in gets its own token, and the account profile answers whose it is."""
    tokens = iter(range(1, 100))
    respx.post(oauth.TOKEN_URL).mock(
        side_effect=lambda _request: httpx.Response(
            200, json={"access_token": f"user-{next(tokens)}", "expires_in": 86399}
        )
    )
    owners: dict[str, int] = {}

    def account(request: httpx.Request) -> httpx.Response:
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        return httpx.Response(200, json={"id": owners[bearer], "wow_accounts": []})

    respx.get(ACCOUNT_URL).mock(side_effect=account)
    mock_battle_net.owners = owners  # type: ignore[attr-defined]


def sign_in(client: TestClient, account_id: int) -> Any:
    """The Battle.net sign-in, as a browser goes through it."""
    owners: dict[str, int] = mock_battle_net.owners  # type: ignore[attr-defined]
    login = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    # The next token the mock hands out is for this account.
    owners[f"user-{len(owners) + 1}"] = account_id
    return client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)


def browser(app: FastAPI) -> TestClient:
    return api_client(app)


def test_users_off_changes_nothing(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/me").json() == {
            "users": False,
            "signed_in": False,
            "admin": False,
            "signups_open": False,
        }
        assert client.get("/api/character").status_code == 200  # no sign-in needed


def test_with_users_on_everything_but_the_public_routes_needs_a_sign_in(
    users_on: Settings, engine: Engine
) -> None:
    with api_client(create_app(users_on, engine)) as client:
        for path in ("/api/character", "/api/status", "/api/characters", "/api/rules"):
            assert client.get(path).status_code == 401, path
        assert client.post("/api/sync").status_code == 401
        for path in ("/api/healthz", "/api/about", "/api/me", "/api/guest"):
            assert client.get(path).status_code == 200, path
        assert client.get("/api/me").json()["users"] is True


@respx.mock
def test_the_first_sign_in_is_the_admin_and_adopts_the_characters(
    users_on: Settings, engine: Engine
) -> None:
    mock_battle_net()
    app = create_app(users_on, engine)
    with browser(app) as admin:  # the start seeds Brumboldt from .env, with no owner
        callback = sign_in(admin, ADMIN)
        assert callback.status_code == 303
        cookie = callback.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
        assert admin.get("/api/me").json() | {"signups_open": False} == {
            "users": True,
            "signed_in": True,
            "admin": True,
            "signups_open": False,
        }
        listed = admin.get("/api/characters").json()["characters"]
        assert [c["slug"] for c in listed] == ["brumboldt-doomlet"]
    with Session(engine) as session:
        (user,) = session.exec(select(User)).all()
        (stored,) = session.exec(select(UserSession)).all()
        assert (user.account_id, user.is_admin) == (ADMIN, True)
        token = admin.cookies.get(COOKIE)
        assert token and stored.token_hash != token  # only the hash is kept
        assert {c.user_id for c in session.exec(select(Character)).all()} == {user.id}


@respx.mock
def test_sign_ups_stay_closed_unless_the_operator_opens_them(
    users_on: Settings, engine: Engine
) -> None:
    mock_battle_net()
    with (
        browser(create_app(users_on, engine)) as admin,
        browser(create_app(users_on, engine)) as stranger,
    ):
        sign_in(admin, ADMIN)
        refused = sign_in(stranger, GUILDMATE)
        assert refused.status_code == 403
        assert "Sign-ups are closed" in refused.json()["detail"]
        assert stranger.get("/api/character").status_code == 401


@respx.mock
def test_two_users_never_see_each_others_characters(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        assert guildmate.get("/api/me").json()["admin"] is False

        brumboldt = admin.get("/api/characters").json()["characters"][0]["id"]
        assert guildmate.get("/api/characters").json()["characters"] == []
        assert guildmate.get("/api/character").json()["level"] is None  # nothing of the admin's
        theirs = {"X-Character-Id": str(brumboldt)}
        for path in ("/api/character", "/api/rules", "/api/gear", "/api/progress"):
            assert guildmate.get(path, headers=theirs).status_code == 404, path
        assert guildmate.post("/api/sync", headers=theirs).status_code == 404
        assert guildmate.delete("/api/character", headers=theirs).status_code == 404

        added = guildmate.post(
            "/api/characters", json={"name": "Thrall", "surname": "Goelson", "region": "eu"}
        ).json()
        mine = {"X-Character-Id": str(added["id"])}
        assert guildmate.get("/api/character", headers=mine).status_code == 200
        assert admin.get("/api/character", headers=mine).status_code == 404  # and back
        assert [c["slug"] for c in admin.get("/api/characters").json()["characters"]] == [
            "brumboldt-doomlet"
        ]


@respx.mock
def test_instance_wide_settings_are_the_admins(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        assert admin.get("/api/notifications").status_code == 200
        assert guildmate.get("/api/notifications").status_code == 403  # webhooks are secret-like
        for path in ("/api/pool/refresh", "/api/items/refresh", "/api/enchants/refresh"):
            assert guildmate.post(path).status_code == 403, path
        assert guildmate.get("/api/enchants/corrections").status_code == 200  # reading is fine
        assert guildmate.put("/api/enchants/corrections/per-slot", json={}).status_code == 403


@respx.mock
def test_each_user_lists_their_own_account(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        route = respx.routes[1]  # the account profile mock
        guildmate.get("/api/account/characters")
        assert route.calls.last.request.headers["Authorization"] == "Bearer user-2"
        admin.get("/api/account/characters")
        assert route.calls.last.request.headers["Authorization"] == "Bearer user-1"


@respx.mock
def test_signing_out_ends_the_session(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    with browser(create_app(users_on, engine)) as client:
        sign_in(client, ADMIN)
        token = client.cookies.get(COOKIE)
        assert client.get("/api/character").status_code == 200
        assert client.post("/api/logout").status_code == 204
        assert client.get("/api/character").status_code == 401
        # The old cookie, replayed, no longer works.
        client.cookies.set(COOKIE, token or "")
        assert client.get("/api/character").status_code == 401


@respx.mock
def test_an_expired_session_needs_a_new_sign_in(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    with browser(create_app(users_on, engine)) as client:
        sign_in(client, ADMIN)
        with Session(engine) as session:
            stored: Any = session.exec(select(UserSession)).one()
            stored.expires_at = utcnow() - timedelta(minutes=1)
            session.add(stored)
            session.commit()
        assert client.get("/api/character").status_code == 401
        with Session(engine) as session:
            assert session.exec(select(UserSession)).all() == []  # cleared away


# --- every route, as two users (#16 step 2) -----------------------------------------------

# Routes that don't resolve a character, by why that's safe. A new route fails the sweep
# until it's placed here or reads its character through get_character_id.
UNSCOPED = {
    # Public with users on: no character data (guest mode reads none, ADR 0017).
    "public": {
        "GET /api/healthz",
        "GET /api/about",
        "GET /api/me",
        "GET /api/guest",
        "GET /api/guest/recommendations",
    },
    # The signed-in user's own: filtered by user, tested above and below.
    "own": {
        "POST /api/logout",
        "DELETE /api/account",
        "GET /api/characters",
        "POST /api/characters",
        "GET /api/account/characters",
    },
    # Instance-wide and the admin's: 403 for everyone else (ADR 0037).
    "admin": {
        "POST /api/pool/refresh",
        "POST /api/enchants/refresh",
        "PUT /api/enchants/corrections/materials/{item_id}",
        "DELETE /api/enchants/corrections/materials/{item_id}",
        "PUT /api/enchants/corrections/crafted/{item_id}",
        "DELETE /api/enchants/corrections/crafted/{item_id}",
        "PUT /api/enchants/corrections/per-slot",
        "DELETE /api/enchants/corrections/per-slot",
        "GET /api/notifications",
        "POST /api/notifications/destinations",
        "PATCH /api/notifications/destinations/{destination_id}",
        "DELETE /api/notifications/destinations/{destination_id}",
        "POST /api/notifications/destinations/{destination_id}/test",
    },
    # Shared reference data, the same for everyone: readable by any signed-in user.
    "shared": {"GET /api/enchants/corrections"},
}
# Character routes that are also admin-only: refused (403) before the character is read.
ADMIN_AND_SCOPED = {"POST /api/items/refresh", "POST /api/talents/refresh"}
PATH_VALUES = {
    "{item_id}": "1",
    "{key}": "mine",
    "{quest_id}": "warrior-quest",
    "{destination_id}": "1",
}


def api_routes(app: FastAPI) -> dict[str, bool]:
    """Every /api route as "METHOD /path", and whether it resolves a character."""
    from fastapi.routing import APIRoute

    from character_planner.app import get_character_id

    def uses(dependant: Any) -> bool:
        return any(d.call is get_character_id or uses(d) for d in dependant.dependencies)

    return {
        f"{method} {route.path}": uses(route.dependant)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods or ()
    }


def url(route: str) -> tuple[str, str]:
    method, path = route.split(" ", 1)
    for placeholder, value in PATH_VALUES.items():
        path = path.replace(placeholder, value)
    return method, path


@respx.mock
def test_every_route_keeps_users_apart(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    routes = api_routes(app)
    classified: set[str] = set().union(*UNSCOPED.values())
    unscoped = {r for r, scoped in routes.items() if not scoped}
    assert unscoped == classified, "classify new routes in UNSCOPED, or scope them"
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        brumboldt = admin.get("/api/characters").json()["characters"][0]["id"]
        theirs = {"X-Character-Id": str(brumboldt)}
        for route in sorted(r for r, scoped in routes.items() if scoped):
            method, path = url(route)
            status = guildmate.request(method, path, headers=theirs, json={}).status_code
            allowed = (403, 404) if route in ADMIN_AND_SCOPED else (404,)
            assert status in allowed, f"{route} answered {status} for another user's character"
        for route in sorted(UNSCOPED["admin"]):
            method, path = url(route)
            assert guildmate.request(method, path, json={}).status_code == 403, route
        for route in sorted(UNSCOPED["public"]):
            method, path = url(route)
            assert admin.request(method, path).status_code != 401, route
        # The admin's character is untouched by all of that.
        assert admin.get("/api/character").status_code == 200
        listed = admin.get("/api/characters").json()["characters"]
        assert [c["id"] for c in listed] == [brumboldt]


# --- deleting an account (#16 step 2) -------------------------------------------------------


@respx.mock
def test_a_user_deletes_their_account_and_everything_in_it(
    users_on: Settings, engine: Engine
) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        added = guildmate.post(
            "/api/characters", json={"name": "Thrall", "surname": "Goelson", "region": "eu"}
        ).json()
        mine = {"X-Character-Id": str(added["id"])}
        rules = guildmate.get("/api/rules", headers=mine).json()["rules"]
        guildmate.put("/api/rules", json=rules | {"per_slot": 1}, headers=mine)

        deleted = guildmate.delete("/api/account")
        assert deleted.status_code == 200
        assert deleted.json()["removed"] == {
            "storedusagerules": 1,
            "character": 1,
            "usersession": 1,
            "usertoken": 1,
            "user": 1,
        }
        assert guildmate.cookies.get(COOKIE) is None
        assert guildmate.get("/api/character").status_code == 401
        assert admin.get("/api/character").status_code == 200  # the admin's is untouched
    with Session(engine) as session:
        assert [u.account_id for u in session.exec(select(User)).all()] == [ADMIN]
        assert [c.slug for c in session.exec(select(Character)).all()] == ["brumboldt-doomlet"]


@respx.mock
def test_the_admin_goes_last(users_on: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        refused = admin.delete("/api/account")
        assert refused.status_code == 409
        assert "Hand the instance over first" in refused.json()["detail"]
        assert guildmate.delete("/api/account").status_code == 200
        assert admin.delete("/api/account").status_code == 200
    with Session(engine) as session:
        assert session.exec(select(User)).all() == []
        assert session.exec(select(Character)).all() == []  # Brumboldt went with the admin


def test_without_users_there_is_no_account_to_delete(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        assert client.delete("/api/account").status_code == 404


@respx.mock
def test_the_operator_can_delete_a_user(
    users_on: Settings,
    engine: Engine,
    cli_settings: Settings,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    from character_planner import dbcli

    mock_battle_net()
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
    assert dbcli.main(["delete-user", str(GUILDMATE)]) == 2  # needs --yes
    assert dbcli.main(["delete-user"]) == 2  # needs an id
    assert dbcli.main(["delete-user", "999", "--yes"]) == 1
    assert dbcli.main(["delete-user", str(ADMIN), "--yes"]) == 1  # the admin goes last
    assert dbcli.main(["delete-user", str(GUILDMATE), "--yes"]) == 0
    assert "Deleted the user" in capsys.readouterr().out
    with Session(engine) as session:
        assert [u.account_id for u in session.exec(select(User)).all()] == [ADMIN]
