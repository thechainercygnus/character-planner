"""Professions: rank milestones and crafted gear (#10, ADR 0031)."""

import json
from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.config import Settings
from character_planner.crafting import (
    CraftedItem,
    crafted_items,
    item_info,
    known_recipes,
    load_profession_data,
    professions_view,
    refresh_crafting,
)
from character_planner.db import BlizzardItem, CraftingRecipe, Snapshot
from character_planner.pool import build_pool
from character_planner.targets import source_text

from .conftest import FIXTURES, REPO_ROOT, tracked
from .test_app import client  # noqa: F401 (the client fixture)
from .test_items import ITEM, RECIPE, mock_battlenet


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# The real professions snapshot: Mining, Engineering, Cooking and First Aid.
PROFESSIONS = fixture("forever_professions")
DATA = load_profession_data(REPO_ROOT / "data" / "curated" / "professions.yaml")


def store_professions(session: Session) -> None:
    session.add(
        Snapshot(
            character_id=tracked(session),
            source="api",
            kind="professions",
            status=200,
            payload=PROFESSIONS,
        )
    )
    session.commit()


def test_known_recipes_come_from_the_professions_snapshot() -> None:
    recipes = known_recipes(PROFESSIONS)
    by_profession: dict[str, int] = {}
    for recipe in recipes:
        by_profession[recipe.profession] = by_profession.get(recipe.profession, 0) + 1
    assert by_profession == {"Mining": 6, "Engineering": 19, "Cooking": 11, "First Aid": 7}
    goggles = next(r for r in recipes if r.name == "Flying Tiger Goggles")
    assert (goggles.recipe_id, goggles.profession) == (2430, "Engineering")
    assert known_recipes(None) == []


def test_a_crafted_armor_piece_as_item_details() -> None:
    info = item_info(fixture("blizzard_item_4368"))  # Flying Tiger Goggles
    assert info is not None
    assert (info.name, info.slot, info.armor_type, info.weapon_type) == (
        "Flying Tiger Goggles",
        "Head",
        "Cloth",
        None,
    )
    assert (info.item_level, info.required_level, info.armor) == (20, None, 27)  # 0: none
    assert info.stats == {"Stamina": 4, "Spirit": 4}
    assert info.quality == "UNCOMMON"
    assert info.wowhead == "https://www.wowhead.com/forever/item=4368"


def test_a_crafted_weapon_as_item_details() -> None:
    info = item_info(fixture("blizzard_item_4362"))  # Rough Boomstick
    assert info is not None
    assert (info.slot, info.weapon_type, info.armor_type) == ("Ranged", "Gun", None)
    assert (info.required_level, info.dps, info.stats) == (5, 4.1, {"Stamina": 1})


def test_items_that_cant_be_equipped_are_not_gear() -> None:
    assert item_info(fixture("blizzard_item_4358")) is None  # Rough Dynamite
    assert item_info(fixture("blizzard_item_8068")) is None  # Crafted Heavy Shot: ammo
    assert item_info({"id": 1}) is None


@respx.mock
def test_refresh_fetches_known_recipes_then_their_items_once(
    engine: Engine, settings: Settings
) -> None:
    mock_battlenet()
    recipes = respx.routes  # the recipe and item routes from mock_battlenet
    with Session(engine) as session:
        store_professions(session)
        first = refresh_crafting(session, settings, tracked(session))
        again = refresh_crafting(session, settings, tracked(session))
        stored = session.exec(select(CraftingRecipe)).all()
        items = {row.item_id: row.found for row in session.exec(select(BlizzardItem)).all()}
        crafted = crafted_items(session, tracked(session))

    # 43 known recipes; three have fixtures, the rest answer 404 and are cached as such.
    assert (first.recipes_fetched, first.items_fetched, first.errors) == (43, 3, [])
    assert (again.recipes_fetched, again.items_fetched) == (0, 0)
    assert sum(row.found for row in stored) == 3 and len(stored) == 43
    assert items == {4368: True, 4362: True, 4358: True}
    # Rough Dynamite isn't gear.
    assert [(c.name, c.profession, c.recipe) for c in crafted] == [
        ("Flying Tiger Goggles", "Engineering", "Flying Tiger Goggles"),
        ("Rough Boomstick", "Engineering", "Rough Boomstick"),
    ]
    calls = [str(c.request.url) for route in recipes for c in route.calls]
    assert sum(url.startswith(RECIPE) for url in calls) == 43
    assert sum(url.startswith(ITEM) for url in calls) == 3


@respx.mock
def test_a_failed_lookup_is_reported_and_tried_again(engine: Engine, settings: Settings) -> None:
    respx.get(f"{RECIPE}2430").mock(
        return_value=httpx.Response(503)
    )  # first: routes match in order
    mock_battlenet()
    with Session(engine) as session:
        store_professions(session)
        result = refresh_crafting(session, settings, tracked(session))
        assert session.get(CraftingRecipe, 2430) is None  # not cached: tried next time
    assert result.errors == ["recipe 2430: HTTP 503"]


def test_no_client_no_requests(engine: Engine, settings: Settings) -> None:
    no_client = settings.model_copy(
        update={"bnet_client_id": "", "bnet_client_secret": SecretStr("")}
    )
    with Session(engine) as session:
        store_professions(session)
        result = refresh_crafting(session, no_client, tracked(session))
    assert result.errors and result.errors[0].startswith("Blizzard token:")


def test_nothing_to_do_before_a_sync(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        assert refresh_crafting(session, settings, tracked(session)).errors == []
        assert crafted_items(session, tracked(session)) == []


@respx.mock
def test_profession_milestones(engine: Engine, settings: Settings) -> None:
    mock_battlenet()
    with Session(engine) as session:
        store_professions(session)
        refresh_crafting(session, settings, tracked(session))
        view = professions_view(session, DATA, 18, tracked(session))
        at_twenty = professions_view(session, DATA, 20, tracked(session))

    rows = {row.name: row for row in view.professions}
    assert list(rows) == ["Mining", "Engineering", "Cooking", "First Aid"]
    engineering = rows["Engineering"]
    assert (engineering.primary, engineering.skill, engineering.max_skill, engineering.rank) == (
        True,
        104,
        150,
        "Journeyman",
    )
    assert engineering.next_rank is not None
    assert (engineering.next_rank.name, engineering.next_rank.train_at_skill) == ("Expert", 125)
    assert (engineering.next_rank.train_at_level, engineering.next_rank.max_skill) == (20, 225)
    assert (engineering.next_rank.skill_ready, engineering.next_rank.level_ready) == (False, False)
    assert engineering.known_recipes == 19
    assert engineering.crafted_gear == ["Flying Tiger Goggles", "Rough Boomstick"]
    assert rows["Mining"].crafted_gear == []
    assert (rows["Cooking"].primary, rows["Cooking"].note) == (
        False,
        "Expert comes from a book; Artisan from a quest in Tanaris.",
    )
    assert at_twenty.professions[1].next_rank is not None
    assert at_twenty.professions[1].next_rank.level_ready


def test_milestones_before_a_sync(engine: Engine) -> None:
    with Session(engine) as session:
        assert professions_view(session, DATA, None, tracked(session)).professions == []


def test_crafted_gear_joins_the_pool() -> None:
    goggles_info = item_info(fixture("blizzard_item_4368"))
    gun_info = item_info(fixture("blizzard_item_4362"))
    assert goggles_info is not None and gun_info is not None
    crafted = [
        CraftedItem(
            item_id=4368,
            name="Flying Tiger Goggles",
            profession="Engineering",
            recipe="Flying Tiger Goggles",
            info=goggles_info,
        ),
        CraftedItem(
            item_id=4362,
            name="Rough Boomstick",
            profession="Engineering",
            recipe="Rough Boomstick",
            info=gun_info,
        ),
    ]
    pool = build_pool([], crafted=crafted)
    [goggles] = pool[4368].sources
    assert (goggles.kind, goggles.profession, goggles.place, goggles.dungeon_id) == (
        "crafted",
        "Engineering",
        "Engineering",
        None,
    )
    assert pool[4368].slot == "head"
    assert (pool[4362].slot, pool[4362].sources[0].min_level) == ("ranged", 5)
    assert source_text(goggles) == "Crafted: Engineering (Flying Tiger Goggles)"


def test_the_professions_api(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/professions").json() == {"level": None, "professions": []}
    for kind in ("profile", "professions"):
        client.post(
            "/api/snapshots/manual", json={"kind": kind, "payload": fixture(f"forever_{kind}")}
        )
    view = client.get("/api/professions").json()
    assert view["level"] == 18
    engineering = view["professions"][1]
    assert (engineering["name"], engineering["rank"], engineering["next_rank"]["name"]) == (
        "Engineering",
        "Journeyman",
        "Expert",
    )
    assert engineering["crafted_gear"] == []  # no crafting refresh yet
