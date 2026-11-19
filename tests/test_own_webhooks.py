"""Alert webhooks are each user's own (#164, ADR 0045): a character's alerts reach only its
owner's webhooks, and system alerts only the admin's."""

from pathlib import Path

import pytest
import respx
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import notify
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import (
    MIGRATIONS,
    Character,
    NotificationDestination,
    User,
    init_db,
)
from character_planner.notify import Digest

from .conftest import tracked_character
from .test_migrations import engine_at
from .test_notify import OTHER, WEBHOOK, _digests, outbox
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in


@pytest.fixture
def users_on(settings: Settings) -> Settings:
    return settings.model_copy(update={"planner_users": True, "planner_signups": True})


def add_hook(client: object, url: str = WEBHOOK, **extra: object) -> object:
    return client.post(  # type: ignore[attr-defined]
        "/api/notifications/destinations", json={"name": "Mine", "url": url, **extra}
    )


@respx.mock
def test_each_user_sees_and_changes_only_their_own_webhooks(
    users_on: Settings, engine: Engine
) -> None:
    mock_battle_net()
    app = create_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        admins = add_hook(admin).json()  # type: ignore[attr-defined]
        hook = admins["destinations"][0]["id"]
        assert admins["destinations"][0]["alerts"] == notify.USER_ALERTS + notify.SYSTEM_ALERTS

        view = guildmate.get("/api/notifications").json()
        assert view["destinations"] == [] and view["recent"] == []
        assert view["system_alerts_to_user"] is False
        assert {a["audience"] for a in view["alerts"]} == {"user"}
        for method, path in [
            ("PATCH", f"/api/notifications/destinations/{hook}"),
            ("DELETE", f"/api/notifications/destinations/{hook}"),
            ("POST", f"/api/notifications/destinations/{hook}/test"),
        ]:
            assert guildmate.request(method, path, json={}).status_code == 404, path

        theirs = add_hook(guildmate, OTHER).json()  # type: ignore[attr-defined]
        (mine,) = theirs["destinations"]
        assert mine["alerts"] == notify.USER_ALERTS  # no system alerts for them
        assert [d["id"] for d in admin.get("/api/notifications").json()["destinations"]] == [hook]
        # System alerts and system destinations stay the admin's.
        refused = guildmate.patch(
            f"/api/notifications/destinations/{mine['id']}", json={"alerts": ["job_failed"]}
        )
        assert refused.status_code == 422
        system = add_hook(guildmate, OTHER, audience="system")
        assert system.status_code == 422  # type: ignore[attr-defined]

        assert guildmate.delete("/api/account").json()["removed"]["notificationdestination"] == 1
    with Session(engine) as session:
        assert [d.id for d in session.exec(select(NotificationDestination)).all()] == [hook]


def own(session: Session, url: str, user_id: int | None) -> NotificationDestination:
    """A user webhook owned by user_id, added as the app adds them."""
    new = notify.NewDestination(name=url[-6:], url=url)
    return notify.add_destination(session, new, user_id)


def two_users(session: Session) -> None:
    session.add_all([User(id=1, account_id=ADMIN, role="admin"), User(id=2, account_id=GUILDMATE)])
    session.commit()


def test_a_characters_alerts_reach_only_its_owners_webhooks(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _digests(monkeypatch, Digest(level=19), Digest(level=20))
    with Session(engine) as session:
        session.add_all(
            [User(id=1, account_id=ADMIN, role="admin"), User(id=2, account_id=GUILDMATE)]
        )
        character = tracked_character(session)
        character.user_id = 2
        session.add(character)
        session.commit()
        admins = own(session, WEBHOOK, 1)
        theirs = own(session, OTHER, 2)

        notify.after_sync(session, settings, session.get(Character, character.id))  # type: ignore[arg-type]
        assert notify.after_sync(session, settings, session.get(Character, character.id)) == 1  # type: ignore[arg-type]
        assert [o.destination_id for o in outbox(session)] == [theirs.id]
        assert admins.id not in {o.destination_id for o in outbox(session)}


def test_system_alerts_go_to_the_admins_webhooks_only(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        session.add_all(
            [User(id=1, account_id=ADMIN, role="admin"), User(id=2, account_id=GUILDMATE)]
        )
        session.commit()
        admins = own(session, WEBHOOK, 1)
        # A user's webhook that somehow lists a system alert still doesn't get it.
        theirs = own(session, OTHER, 2)
        theirs.alerts = [*notify.USER_ALERTS, "job_failed"]
        session.add(theirs)
        session.commit()
        notify.job_failed(session, settings, "sync", "boom")
        assert [o.destination_id for o in outbox(session)] == [admins.id]


def test_without_users_every_webhook_is_the_one_persons(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _digests(monkeypatch, Digest(level=19), Digest(level=20))
    with Session(engine) as session:
        hook = own(session, WEBHOOK, None)
        notify.after_sync(session, settings, tracked_character(session))
        assert notify.after_sync(session, settings, tracked_character(session)) == 1
        notify.job_failed(session, settings, "sync", "boom")
        assert {o.destination_id for o in outbox(session)} == {hook.id}


@respx.mock
def test_the_first_sign_in_adopts_the_webhooks(users_on: Settings, engine: Engine) -> None:
    with Session(engine) as session:
        hook = own(session, WEBHOOK, None)
    mock_battle_net()
    with browser(create_app(users_on, engine)) as admin:
        sign_in(admin, ADMIN)
        (shown,) = admin.get("/api/notifications").json()["destinations"]
        assert shown["id"] == hook.id
    with Session(engine) as session:
        stored = session.get(NotificationDestination, hook.id)
        admin_user = session.exec(select(User)).one()
        assert stored is not None and stored.user_id == admin_user.id


def test_an_instance_with_an_admin_hands_them_its_webhooks(tmp_path: Path) -> None:
    from alembic import command

    engine = engine_at(tmp_path)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0014")
        connection.execute(
            text(
                'INSERT INTO "user" (id, account_id, is_admin, created_at, last_sign_in_at) '
                "VALUES (7, 1001, true, '2026-11-14 00:00:00', '2026-11-14 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO notificationdestination (name, kind, audience, url, alerts, enabled, "
                "created_at) VALUES ('Hook', 'discord_webhook', 'user', 'u', '[]', true, "
                "'2026-11-14 00:00:00')"
            )
        )
    init_db(engine)
    with Session(engine) as session:
        (stored,) = session.exec(select(NotificationDestination)).all()
        assert stored.user_id == 7
