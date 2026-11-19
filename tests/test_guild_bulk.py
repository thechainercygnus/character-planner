"""Your guilds (#215, ADR 0059): the picker's list, joining with several characters at once,
and alts shown as one player only when their player opts in. The guild view's fixtures:
the tank's player has an alt in the same guild, and one in another."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import GuildMembership
from character_planner.recommend import Recommendations

from .test_guild import GUILD, OTHER_GUILD, Player, dungeon, guild_app, players, store  # noqa: F401

US = {"region": "us", "guild_id": GUILD["id"]}


def add_alt(tank: Player, engine: Engine, name: str, level: int, guild: dict[str, Any]) -> int:
    added = tank.client.post(
        "/api/characters", json={"name": name, "surname": "Alt", "region": "us"}
    ).json()
    store(engine, added["id"], "Warrior", "Arms", level, guild)
    return int(added["id"])


def members(tank: Player, change: dict[str, Any]) -> Any:
    response = tank.client.put("/api/guilds/members", json={**US, **change})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_picker_lists_each_guild_with_your_characters_in_it(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
) -> None:
    tank = players["tank"]
    alt = add_alt(tank, engine, "Brumalt", 15, GUILD)
    elsewhere = add_alt(tank, engine, "Brumelse", 12, OTHER_GUILD)
    guilds = tank.client.get("/api/guilds").json()["guilds"]
    assert [(g["name"], g["grouped"]) for g in guilds] == [
        ("Daves Discount Meats", False),
        ("Someone Else's Guild", False),
    ]
    assert [(c["id"], c["joined"]) for c in guilds[0]["characters"]] == [
        (tank.id, False),
        (alt, False),
    ]
    assert [c["id"] for c in guilds[1]["characters"]] == [elsewhere]


def test_join_with_several_at_once_and_leave_with_one(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
) -> None:
    tank = players["tank"]
    alt = add_alt(tank, engine, "Brumalt", 15, GUILD)
    joined = members(tank, {"join": [tank.id, alt], "role": "tank", "shared_alerts": ["level_up"]})
    (guild,) = [g for g in joined["guilds"] if g["guild_id"] == GUILD["id"]]
    assert [(c["joined"], c["role"]) for c in guild["characters"]] == [
        (True, "tank"),
        (True, "tank"),
    ]
    with Session(engine) as session:
        rows = session.exec(select(GuildMembership)).all()
        assert {r.character_id: r.shared_alerts for r in rows} == {
            tank.id: ["level_up"],
            alt: ["level_up"],
        }

    left = members(tank, {"leave": [alt]})
    (guild,) = [g for g in left["guilds"] if g["guild_id"] == GUILD["id"]]
    assert [c["joined"] for c in guild["characters"]] == [True, False]
    assert tank.guild()["opted_in"] is True  # the main stays in


def test_only_your_own_characters_in_that_guild(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
) -> None:
    tank, healer = players["tank"], players["healer"]
    elsewhere = add_alt(tank, engine, "Brumelse", 12, OTHER_GUILD)
    theirs = healer.client.put("/api/guilds/members", json={**US, "join": [tank.id]})
    assert theirs.status_code == 404
    wrong_guild = tank.client.put("/api/guilds/members", json={**US, "join": [tank.id, elsewhere]})
    assert wrong_guild.status_code == 404
    with Session(engine) as session:  # checked before anything changed
        assert session.exec(select(GuildMembership)).all() == []


def going_for(viewer: Player, **params: Any) -> list[int]:
    return list(viewer.guild(**params)["going"])


def test_alts_stay_apart_unless_their_player_groups_them(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
) -> None:
    tank, healer = players["tank"], players["healer"]
    alt = add_alt(tank, engine, "Brumalt", 15, GUILD)
    members(tank, {"join": [tank.id, alt]})
    healer.join()

    # Off (the default): two separate members, nothing linking them, both going.
    seen = healer.guild()
    by_id = {m["character_id"]: m for m in seen["members"]}
    assert by_id[tank.id]["player"] is None and by_id[alt]["player"] is None
    assert not by_id[tank.id]["yours"] and not by_id[alt]["yours"]
    assert {tank.id, alt} <= set(seen["going"])

    # On: one player. Going picks one of them: the higher level, unless asked otherwise.
    grouped = tank.client.put("/api/guilds/grouping", json={**US, "grouped": True}).json()
    assert [g["grouped"] for g in grouped["guilds"] if g["guild_id"] == GUILD["id"]] == [True]
    seen = healer.guild()
    by_id = {m["character_id"]: m for m in seen["members"]}
    assert by_id[tank.id]["player"] == by_id[alt]["player"] is not None
    assert by_id[healer.id]["player"] is None
    assert tank.id in seen["going"] and alt not in seen["going"]  # level 19 over 15
    assert going_for(healer, going=[alt, tank.id, healer.id]) == [alt, healer.id]
    # The tank's own alt, viewed from it, is the one going.
    assert alt in going_for(Player(tank.client, alt))

    # Off again: apart at once.
    tank.client.put("/api/guilds/grouping", json={**US, "grouped": False})
    assert all(m["player"] is None for m in healer.guild()["members"])


def test_a_grouped_player_counts_once_in_the_ranking(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tank, healer = players["tank"], players["healer"]
    alt = add_alt(tank, engine, "Brumalt", 15, GUILD)
    per_member = {
        tank.id: [dungeon("deadmines", 17, 26, ("Cape", 6.0))],
        alt: [dungeon("deadmines", 17, 26, ("Belt", 5.0))],
        healer.id: [dungeon("deadmines", 17, 26, ("Robe", 4.0))],
    }

    def fake(_session: Session, _settings: Settings, character_id: int | None) -> Recommendations:
        dungeons = per_member.get(character_id or 0, [])
        return Recommendations(
            level=None, window=None, rows=[], dungeons=dungeons, considered=0, unscored=0
        )

    monkeypatch.setattr(jobs, "recommendations_for", fake)
    members(tank, {"join": [tank.id, alt]})
    healer.join()
    apart = healer.guild()["dungeons"][0]["total_gain"]
    assert apart == 15.0  # both of the tank's characters counted
    tank.client.put("/api/guilds/grouping", json={**US, "grouped": True})
    together = healer.guild()
    assert together["dungeons"][0]["total_gain"] == 10.0  # the tank once, on the main
    assert together["roles"] == {"tank": 1, "healer": 1, "dps": 0}


def test_without_users_there_are_no_guilds(settings: Settings, engine: Engine) -> None:
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/api/guilds").status_code == 404


def test_your_grouping_is_in_your_export(
    players: dict[str, Player],  # noqa: F811
    engine: Engine,
) -> None:
    import io
    import json
    import zipfile

    tank = players["tank"]
    tank.client.put("/api/guilds/grouping", json={**US, "grouped": True})
    archive = zipfile.ZipFile(io.BytesIO(tank.client.get("/api/account/export").content))
    (row,) = json.loads(archive.read("guild_grouping.json"))
    assert (row["region"], row["guild_id"]) == ("us", GUILD["id"])
