# ruff: noqa: F811 - pytest fixtures imported from test_guild, then named as parameters
"""Guild-channel alerts (#163, ADR 0046): any member in the guild view sets the guild's
Discord webhook, and each member picks which of their alerts post there."""

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import notify
from character_planner.config import Settings
from character_planner.db import Character, NotificationDestination
from character_planner.notify import Digest

from .test_guild import OTHER_GUILD, Player, guild_app, players, store  # noqa: F401
from .test_notify import OTHER, WEBHOOK, _digests, outbox


def set_channel(player: Player, url: str = WEBHOOK) -> Any:
    return player.client.put("/api/guild/channel", json={"url": url}, headers=player.headers)


def share(player: Player, *alerts: str) -> Any:
    return player.client.put(
        "/api/guild/shared-alerts", json={"alerts": list(alerts)}, headers=player.headers
    )


def channels(engine: Engine) -> list[NotificationDestination]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(NotificationDestination).where(NotificationDestination.kind == notify.GUILD)
            ).all()
        )


def test_any_member_in_the_view_sets_the_channel_and_all_see_it(
    players: dict[str, Player],
) -> None:
    tank, healer, dps = players["tank"], players["healer"], players["dps"]
    tank.join()
    healer.join()
    assert set_channel(dps).status_code == 403  # in the guild, not in the view
    assert set_channel(players["outsider"]).status_code == 403
    assert set_channel(tank, "https://example.com/hook").status_code == 422

    view = set_channel(tank).json()
    assert view["channel"]["url"].endswith("/••••")  # the token never comes back
    assert view["channel"]["set_by"] == "Brum Doomlet"
    assert healer.guild()["channel"]["set_by"] == "Brum Doomlet"
    assert dps.guild()["channel"] is None  # nothing until they join

    # Another member replaces it; every member sees who did.
    assert set_channel(healer, OTHER).json()["channel"]["set_by"] == "Hollie Light"
    assert tank.guild()["channel"]["set_by"] == "Hollie Light"
    removed = tank.client.delete("/api/guild/channel", headers=tank.headers)
    assert removed.json()["channel"] is None


def test_sharing_starts_empty_and_takes_character_alerts_only(
    players: dict[str, Player],
) -> None:
    tank = players["tank"]
    tank.join()
    view = tank.guild()
    assert view["shared_alerts"] == []
    assert {a["kind"] for a in view["alerts"]} == set(notify.USER_ALERTS)
    assert share(tank, "level_up", "target_reached").json()["shared_alerts"] == [
        "level_up",
        "target_reached",
    ]
    assert share(tank, "job_failed").status_code == 422
    assert share(players["dps"], "level_up").status_code == 403  # not in the view


def test_only_what_a_member_shares_posts_to_the_channel(
    players: dict[str, Player], engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tank, healer = players["tank"], players["healer"]
    for player in (tank, healer):
        player.join()
    set_channel(tank)
    share(tank, "level_up")  # the healer shares nothing
    (channel,) = channels(engine)
    _digests(
        monkeypatch,
        Digest(level=19),
        Digest(level=20, targets={"BACK": "1"}, names={"1": "Cape"}),
        Digest(level=20),
        Digest(level=21),
    )
    with Session(engine) as session:
        for player in (tank, tank, healer, healer):
            character = session.get(Character, player.id)
            assert character is not None
            notify.after_sync(session, settings, character)
        (posted,) = [o for o in outbox(session) if o.destination_id == channel.id]
    fields = [f["name"] for f in posted.payload["embeds"][0]["fields"]]
    assert fields == ["Level-up"]  # not the target in reach: the tank didn't share that
    assert posted.payload["embeds"][0]["title"] == "Brum Doomlet: what changed"


def test_a_member_who_left_the_guild_stops_sharing(
    players: dict[str, Player], engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tank, healer = players["tank"], players["healer"]
    tank.join()
    healer.join()
    set_channel(tank)
    share(healer, "level_up")
    store(engine, healer.id, "Priest", "Holy", 20, OTHER_GUILD)
    _digests(monkeypatch, Digest(level=20), Digest(level=21))
    with Session(engine) as session:
        for _ in range(2):
            character = session.get(Character, healer.id)
            assert character is not None
            notify.after_sync(session, settings, character)
        assert outbox(session) == []


def test_the_channel_goes_with_the_last_member(players: dict[str, Player], engine: Engine) -> None:
    tank, healer = players["tank"], players["healer"]
    tank.join()
    healer.join()
    set_channel(tank)
    tank.join(opted_in=False)
    assert len(channels(engine)) == 1  # the healer is still there
    assert healer.guild()["channel"]["set_by"] is None  # its setter left the view
    assert healer.client.delete("/api/character", headers=healer.headers).status_code == 200
    assert channels(engine) == []


@respx.mock
def test_a_test_message_goes_to_the_channel(players: dict[str, Player]) -> None:
    tank = players["tank"]
    tank.join()
    hook = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    assert tank.client.post("/api/guild/channel/test", headers=tank.headers).status_code == 404
    set_channel(tank)
    sent = tank.client.post("/api/guild/channel/test", headers=tank.headers)
    assert sent.json()["ok"] is True and hook.called


def test_a_guild_channel_is_nobodys_alert_settings_and_gets_no_system_alerts(
    players: dict[str, Player], engine: Engine, settings: Settings
) -> None:
    tank = players["tank"]
    tank.join()
    set_channel(tank)
    assert tank.client.get("/api/notifications").json()["destinations"] == []
    with Session(engine) as session:
        notify.job_failed(session, settings, "sync", "boom")
        assert outbox(session) == []
