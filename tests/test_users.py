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
