"""The guild view (#18, ADR 0042), from multi-character fixtures: three Battle.net accounts,
one character each, in Daves Discount Meats, and one from another guild."""

from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import Snapshot
from character_planner.pool import PoolItem, PoolSource
from character_planner.recommend import DungeonUpgrade, DungeonValue, Recommendations

from .conftest import api_client
from .test_users import mock_battle_net, sign_in

GUILD = {"id": 670649, "name": "Daves Discount Meats"}
OTHER_GUILD = {"id": 111, "name": "Someone Else's Guild"}


def store(
    engine: Engine, character_id: int, cls: str, spec: str, level: int, guild: dict[str, Any] | None
) -> None:
    """A synced profile and talents, as the Forever API shapes them."""
    profile: dict[str, Any] = {"level": level, "character_class": {"name": cls}}
    if guild is not None:
        profile["guild"] = guild
    specs = {
        "specialization_groups": [
            {
                "is_active": True,
                "specializations": [
                    {"specialization_name": spec, "spent_points": 10, "talents": []}
                ],
            }
        ]
    }
    with Session(engine) as session:
        for kind, payload in (("profile", profile), ("specializations", specs)):
            session.add(
                Snapshot(
                    character_id=character_id, source="api", kind=kind, status=200, payload=payload
                )
            )
        session.commit()


class Player:
    def __init__(self, client: TestClient, character_id: int) -> None:
        self.client, self.id = client, character_id
        self.headers = {"X-Character-Id": str(character_id)}

    def guild(self, **params: Any) -> Any:
        response = self.client.get("/api/guild", headers=self.headers, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def join(self, opted_in: bool = True, role: str | None = None) -> Any:
        return self.client.put(
            "/api/guild/membership",
            json={"opted_in": opted_in, "role": role},
            headers=self.headers,
        )


@pytest.fixture
def guild_app(settings: Settings, engine: Engine) -> FastAPI:
    on = settings.model_copy(update={"planner_users": True, "planner_signups": True})
    return create_app(on, engine)


@pytest.fixture
def players(guild_app: FastAPI, engine: Engine) -> Iterator[dict[str, Player]]:
    """Four signed-in accounts, each with one character, synced."""
    with respx.mock:
        mock_battle_net()
        people = {
            "tank": ("Brum", "Doomlet", "Warrior", "Protection", 19, GUILD),
            "healer": ("Hollie", "Light", "Priest", "Holy", 20, GUILD),
            "dps": ("Fizz", "Bang", "Mage", "Fire", 31, GUILD),
            "outsider": ("Otto", "Side", "Rogue", "Combat", 20, OTHER_GUILD),
        }
        result: dict[str, Player] = {}
        clients: list[TestClient] = []
        for account, (key, (name, surname, cls, spec, level, guild)) in enumerate(
            people.items(), start=1
        ):
            client = api_client(guild_app)
            client.__enter__()
            clients.append(client)
            sign_in(client, 1000 + account)
            added = client.post(
                "/api/characters", json={"name": name, "surname": surname, "region": "us"}
            ).json()
            store(engine, added["id"], cls, spec, level, guild)
            result[key] = Player(client, added["id"])
        yield result
        for client in clients:
            client.__exit__(None, None, None)


def test_the_guild_view_needs_users_on(settings: Settings, engine: Engine) -> None:
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/guild").status_code == 404


def test_before_opting_in_a_member_sees_only_the_guilds_name(players: dict[str, Player]) -> None:
    players["healer"].join()  # someone else has opted in
    view = players["tank"].guild()
    assert view["guild"] == GUILD
    assert (view["opted_in"], view["members"], view["dungeons"]) == (False, [], [])


def test_opted_in_members_see_each_other_and_their_roles(players: dict[str, Player]) -> None:
    for key in ("tank", "healer", "dps", "outsider"):
        assert players[key].join().status_code == 200
    view = players["tank"].guild()
    assert view["opted_in"] is True
    assert [(m["name"], m["role"], m["spec"], m["yours"]) for m in view["members"]] == [
        ("Brum Doomlet", "tank", "Protection", True),  # yours first
        ("Fizz Bang", "dps", "Fire", False),
        ("Hollie Light", "healer", "Holy", False),
    ]  # the outsider's guild is another one
    assert view["roles"] == {"tank": 1, "healer": 1, "dps": 1}
    assert view["missing_roles"] == []
    # The outsider sees only their own guild.
    assert [m["name"] for m in players["outsider"].guild()["members"]] == ["Otto Side"]


def test_a_member_can_choose_their_role(players: dict[str, Player]) -> None:
    players["tank"].join()
    players["dps"].join(role="healer")  # an off-spec healer tonight
    view = players["tank"].guild()
    assert {m["name"]: m["role"] for m in view["members"]} == {
        "Brum Doomlet": "tank",
        "Fizz Bang": "healer",
    }
    assert players["dps"].guild()["role"] == "healer"


def test_a_group_missing_a_role_is_flagged(players: dict[str, Player]) -> None:
    for key in ("tank", "dps"):
        players[key].join()
    assert players["tank"].guild()["missing_roles"] == ["healer"]


def test_opting_out_and_leaving_the_guild_both_drop_a_member(
    players: dict[str, Player], engine: Engine
) -> None:
    for key in ("tank", "healer", "dps"):
        players[key].join()
    players["dps"].join(opted_in=False)
    store(engine, players["healer"].id, "Priest", "Holy", 20, OTHER_GUILD)  # left the guild
    assert [m["name"] for m in players["tank"].guild()["members"]] == ["Brum Doomlet"]


def test_a_guildless_character_cannot_opt_in(players: dict[str, Player], engine: Engine) -> None:
    store(engine, players["dps"].id, "Mage", "Fire", 31, None)
    refused = players["dps"].join()
    assert refused.status_code == 409
    assert "isn't in a guild" in refused.json()["detail"]


def test_deleting_a_character_takes_its_membership(players: dict[str, Player]) -> None:
    players["tank"].join()
    players["healer"].join()
    healer = players["healer"]
    assert healer.client.delete("/api/character", headers=healer.headers).status_code == 200
    assert [m["name"] for m in players["tank"].guild()["members"]] == ["Brum Doomlet"]


# --- the group ranking ------------------------------------------------------------------------


def dungeon(dungeon_id: str, low: int, high: int, *gains: tuple[str, float]) -> DungeonValue:
    source = PoolSource(
        kind="drop", dungeon_id=dungeon_id, dungeon=dungeon_id.title(), detail="Boss"
    )
    upgrades = [
        DungeonUpgrade(
            slot="BACK",
            item=PoolItem(
                item_id=sum(map(ord, name)), name=name, item_slot="Back", sources=[source]
            ),
            score_gain=gain,
            source=source,
        )
        for name, gain in gains
    ]
    return DungeonValue(
        dungeon_id=dungeon_id,
        dungeon=dungeon_id.title(),
        min_level=low,
        max_level=high,
        total_gain=round(sum(g for _, g in gains), 2),
        upgrades=upgrades,
    )


def test_dungeons_rank_by_what_the_group_going_would_take(
    players: dict[str, Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = {key: p.id for key, p in players.items()}
    per_member = {
        ids["tank"]: [
            dungeon("deadmines", 17, 26, ("Cape", 6.0)),
            dungeon("wailing", 17, 24, ("Belt", 2.0)),
        ],
        ids["healer"]: [dungeon("deadmines", 17, 26, ("Robe", 4.0), ("Wand", 1.5))],
        ids["dps"]: [dungeon("wailing", 17, 24, ("Staff", 9.0))],
    }

    def fake(_session: Session, _settings: Settings, character_id: int | None) -> Recommendations:
        return Recommendations(
            level=None,
            window=None,
            rows=[],
            dungeons=per_member.get(character_id or 0, []),
            considered=0,
            unscored=0,
        )

    monkeypatch.setattr(jobs, "recommendations_for", fake)
    for key in ("tank", "healer", "dps"):
        players[key].join()

    everyone = players["tank"].guild()
    assert [(d["dungeon_id"], d["total_gain"]) for d in everyone["dungeons"]] == [
        ("deadmines", 11.5),
        ("wailing", 11.0),
    ]
    deadmines = everyone["dungeons"][0]
    assert sorted(deadmines["in_range"]) == sorted([ids["tank"], ids["healer"]])
    assert [n["item"] for n in deadmines["needs"][str(ids["healer"])]] == ["Robe", "Wand"]
    wailing = everyone["dungeons"][1]
    assert ids["dps"] not in wailing["in_range"]  # level 31: past The Wailing Caverns

    # Just the tank and the mage going: Wailing Caverns is worth more to them.
    pair = players["tank"].guild(going=[ids["tank"], ids["dps"]])
    assert [(d["dungeon_id"], d["total_gain"]) for d in pair["dungeons"]] == [
        ("wailing", 11.0),
        ("deadmines", 6.0),
    ]
    assert pair["missing_roles"] == ["healer"]
    assert pair["going"] == [ids["tank"], ids["dps"]]
