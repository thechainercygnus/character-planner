"""Sign-ups and invites (#239, ADR 0057): opened or closed in the app, which wins over
PLANNER_SIGNUPS from then on, and one-use invites that let one person in while they're
closed. The admin, a guildmate and a third account throughout."""

import json
from datetime import timedelta

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from character_planner import admin_log, signups
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import Invite, User, utcnow

from .test_signup import API, BOT, BOT_TOKEN, CHANNEL, OURS, a_message, mock_discord, pinned
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in

THIRD = 3003


@pytest.fixture
def users(settings: Settings) -> Settings:
    return settings.model_copy(update={"planner_users": True})


def accounts(engine: Engine) -> list[int]:
    with Session(engine) as session:
        return [u.account_id for u in session.exec(select(User).order_by(col(User.id)))]


def actions(engine: Engine) -> list[tuple[str, str | None]]:
    with Session(engine) as session:
        return [(e.action, e.detail) for e in reversed(admin_log.recent(session))]


def closed_app(settings: Settings, engine: Engine) -> FastAPI:
    return create_app(settings, engine)  # PLANNER_SIGNUPS off


@respx.mock
def test_the_app_opens_and_closes_sign_ups_over_the_setting(
    users: Settings, engine: Engine
) -> None:
    mock_battle_net()
    app = closed_app(users, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        view = admin.get("/api/admin/signups").json()
        assert view["signups"] == {"open": False, "source": "setting", "changed_at": None}
        assert view["setting"] is False
        assert sign_in(guildmate, GUILDMATE).status_code == 403

        opened = admin.put("/api/admin/signups", json={"open": True}).json()
        assert opened["signups"]["open"] and opened["signups"]["source"] == "app"
        assert guildmate.get("/api/me").json()["signups_open"] is True
        assert sign_in(guildmate, GUILDMATE).status_code == 303
    assert accounts(engine) == [ADMIN, GUILDMATE]

    # Closed in the app: closed for good, even with PLANNER_SIGNUPS on.
    reopened = create_app(users.model_copy(update={"planner_signups": True}), engine)
    with browser(reopened) as admin, browser(reopened) as third:
        sign_in(admin, ADMIN)
        admin.put("/api/admin/signups", json={"open": False})
        assert third.get("/api/me").json()["signups_open"] is False
        assert sign_in(third, THIRD).status_code == 403
    assert accounts(engine) == [ADMIN, GUILDMATE]
    assert actions(engine) == [("signups.change", "opened"), ("signups.change", "closed")]


@respx.mock
def test_an_invite_lets_one_person_in_once(users: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = closed_app(users, engine)
    with browser(app) as admin, browser(app) as guildmate, browser(app) as third:
        sign_in(admin, ADMIN)
        created = admin.post("/api/admin/invites").json()
        token = created["token"]
        assert created["invite"]["state"] == "open"
        assert created["invite"]["created_by_account_id"] == ADMIN

        held = guildmate.post("/auth/invite", json={"token": token})
        assert held.status_code == 204
        cookie = held.headers["set-cookie"]
        assert "planner_invite=" in cookie and "HttpOnly" in cookie
        assert sign_in(guildmate, GUILDMATE).status_code == 303
        assert "planner_invite" not in guildmate.cookies  # gone with the callback

        # Spent: nobody else gets in on it, whether they ask first or carry it in.
        assert third.post("/auth/invite", json={"token": token}).status_code == 404
        third.cookies.set("planner_invite", token)
        refused = sign_in(third, THIRD)
        assert refused.status_code == 403 and "used, revoked or has expired" in refused.text

        (invite,) = admin.get("/api/admin/signups").json()["invites"]
        assert (invite["state"], invite["used_by_account_id"]) == ("used", GUILDMATE)
    assert accounts(engine) == [ADMIN, GUILDMATE]
    with Session(engine) as session:  # only the token's hash is stored
        stored = session.exec(select(Invite)).one()
        assert token not in json.dumps(stored.model_dump(mode="json"))


@respx.mock
def test_an_existing_account_never_spends_an_invite(users: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        admin.put("/api/admin/signups", json={"open": False})
        token = admin.post("/api/admin/invites").json()["token"]
        guildmate.post("/auth/invite", json={"token": token})
        assert sign_in(guildmate, GUILDMATE).status_code == 303
        (invite,) = admin.get("/api/admin/signups").json()["invites"]
        assert invite["state"] == "open"


@respx.mock
def test_revoked_and_expired_invites_stop_working(users: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = closed_app(users, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        revoked = admin.post("/api/admin/invites").json()
        expired = admin.post("/api/admin/invites").json()
        gone = admin.delete(f"/api/admin/invites/{revoked['invite']['id']}")
        assert gone.status_code == 200 and gone.json()["state"] == "revoked"
        assert admin.delete(f"/api/admin/invites/{revoked['invite']['id']}").status_code == 409
        assert admin.delete("/api/admin/invites/999").status_code == 404
        with Session(engine) as session:
            row = session.get(Invite, expired["invite"]["id"])
            assert row is not None
            row.expires_at = utcnow() - timedelta(minutes=1)
            session.add(row)
            session.commit()
        for created in (revoked, expired):
            assert (
                guildmate.post("/auth/invite", json={"token": created["token"]}).status_code == 404
            )
        states = [i["state"] for i in admin.get("/api/admin/signups").json()["invites"]]
        assert states == ["expired", "revoked"]  # newest first
    assert ("invite.revoke", f"invite {revoked['invite']['id']}") in actions(engine)
    assert actions(engine).count(("invite.create", f"invite {revoked['invite']['id']}")) == 1


@respx.mock
def test_sign_ups_are_the_admins_alone(users: Settings, engine: Engine) -> None:
    mock_battle_net()
    app = create_app(users.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as admin, browser(app) as superuser:
        sign_in(admin, ADMIN)
        sign_in(superuser, GUILDMATE)
        theirs = next(
            a["user_id"]
            for a in admin.get("/api/admin/accounts").json()["accounts"]
            if a["account_id"] == GUILDMATE
        )
        admin.put(f"/api/admin/users/{theirs}/role", json={"role": "superuser"})
        assert superuser.get("/api/admin/signups").status_code == 403
        assert superuser.put("/api/admin/signups", json={"open": False}).status_code == 403
        assert superuser.post("/api/admin/invites").status_code == 403


def test_without_users_there_are_no_invites(settings: Settings, engine: Engine) -> None:
    with TestClient(create_app(settings, engine)) as client:
        assert client.post("/auth/invite", json={"token": "x" * 32}).status_code == 404
        assert client.get("/api/admin/signups").status_code == 404


def test_closed_invites_are_pruned_after_a_month(engine: Engine) -> None:
    now = utcnow()
    with Session(engine) as session:
        session.add_all(
            [
                Invite(token_hash="open", expires_at=now + timedelta(days=3)),
                Invite(token_hash="used", expires_at=now, used_at=now - timedelta(days=31)),
                Invite(token_hash="recent", expires_at=now, used_at=now - timedelta(days=2)),
                Invite(token_hash="revoked", expires_at=now, revoked_at=now - timedelta(days=40)),
                Invite(token_hash="expired", expires_at=now - timedelta(days=31)),
            ]
        )
        session.commit()
        assert signups.prune(session) == 3
        kept = {i.token_hash for i in session.exec(select(Invite))}
    assert kept == {"open", "recent"}


@respx.mock
def test_the_discord_message_follows_the_app(users: Settings, engine: Engine) -> None:
    mock_battle_net()
    configured = users.model_copy(
        update={"discord_bot_token": SecretStr(BOT_TOKEN), "discord_signup_channel_id": CHANNEL}
    )
    routes = mock_discord(pinned(a_message(OURS, BOT, signup_marker())))
    app = create_app(configured, engine)
    with browser(app) as admin:
        sign_in(admin, ADMIN)
        admin.put("/api/admin/signups", json={"open": True})
    edit = routes["edit"].calls.last.request
    assert "Sign-ups are open." in json.loads(edit.content)["content"]
    assert API in str(edit.url)


def signup_marker() -> str:
    from character_planner import signup

    return signup.MARKER
