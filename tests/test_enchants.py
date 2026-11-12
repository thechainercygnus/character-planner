import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.companion import CompanionInfo
from character_planner.config import Settings
from character_planner.db import RecipeData
from character_planner.enchants import (
    WEAPON_DAMAGE,
    catalog,
    parse_effects,
    parse_recipe,
    reagent_and_crafted_ids,
    refresh_recipes,
)

from .conftest import FIXTURES

# Real Forever responses from the 2026-11-12 recipe probe, trimmed to 12 recipes.
TIER: dict[str, Any] = json.loads(
    (FIXTURES / "blizzard_skill_tier_enchanting.json").read_text(encoding="utf-8")
)
RECIPES: dict[str, Any] = json.loads(
    (FIXTURES / "blizzard_recipes_enchanting.json").read_text(encoding="utf-8")
)
CATEGORY = {r["id"]: c["name"] for c in TIER["categories"] for r in c["recipes"]}


def option(recipe_id: int, items: dict[int, CompanionInfo] | None = None):
    parsed = parse_recipe(RECIPES[str(recipe_id)], "Enchanting", CATEGORY[recipe_id], items or {})
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("recipe_id", "effects"),
    [
        (4290, {"Stamina": 2}),  # "...increases the Stamina of the wearer by 2."
        (4402, {"Stamina": 3}),  # "...increase the wearer's Stamina by 3."
        (4293, {"Defense": 3}),  # "...defense skill of the wearer is increased by 3."
        (7377, {"Armor": 20}),  # "...increase armor by 20."
        (7501, dict.fromkeys(["Strength", "Agility", "Stamina", "Intellect", "Spirit"], 1)),
        (4367, {WEAPON_DAMAGE: 1}),  # "...to do 1 additional point of damage."
        (4368, {WEAPON_DAMAGE: 4}),
        (7528, {"Block %": 2}),
        (4300, {f"{s} Resistance": 2 for s in ("Fire", "Frost", "Nature", "Shadow", "Arcane")}),
        (51763, {"Agility": 9}),  # "...increase Agility by 9."
        (7669, {}),  # movement speed: nothing to weigh
        (54407, {}),  # Recovery: a proc
    ],
)
def test_effects_from_real_descriptions(recipe_id: int, effects: dict[str, float]) -> None:
    assert option(recipe_id).effects == effects


@pytest.mark.parametrize(
    ("text", "effects"),
    [
        ("Enchanted: Scope (+1 Damage)", {WEAPON_DAMAGE: 1}),  # equipped display text
        ("Permanently enchant a Cloak to add 5 to agility.", {"Agility": 5}),
        ("Permanently enchant a shield to give 3 spirit.", {"Spirit": 3}),
        ("Permanently enchant bracers to give +9 defense skill.", {"Defense": 9}),
        ("Permanently enchant a cloak to give 30 additional armor.", {"Armor": 30}),
        ("Permanently enchant a cloak to give 12 Fire Resistance.", {"Fire Resistance": 12}),
        (
            "Permanently enchant a cloak so that it increases resistance to fire by 10.",
            {"Fire Resistance": 10},
        ),
        ("Permanently enchant a Melee Weapon to do 6 additional points of damage to Beasts.", {}),
        ("...heals for 75 to 125 and increases Strength by 100 for 15 sec.", {}),  # a proc
        (None, {}),
    ],
)
def test_effects_from_other_phrasings(text: str | None, effects: dict[str, float]) -> None:
    assert parse_effects(text) == effects


def test_slots_and_flags() -> None:
    assert option(4402).slots == ["FEET"]
    assert option(7377).slots == ["BACK"]
    impact = option(4368)
    assert (impact.slots, impact.two_handed) == (["MAIN_HAND"], True)
    block = option(7528)
    assert (block.slots, block.shield_only) == (["OFF_HAND"], True)
    sod = option(51763)  # in the SEASON OF DISCOVERY category: slot from the name
    assert (sod.slots, sod.season_of_discovery) == (["WRIST"], True)
    assert option(4367).season_of_discovery is False


def test_level_estimate_is_the_highest_reagent_item_level() -> None:
    items = {
        10940: CompanionInfo(item_id=10940, name="Strange Dust", item_level=25),
        10938: CompanionInfo(item_id=10938, name="Lesser Magic Essence", item_level=10),
        10978: CompanionInfo(item_id=10978, name="Small Glimmering Shard", item_level=20),
    }
    assert option(4367, items).estimated_level == 25  # dust, essence, shard
    assert option(4293, items).estimated_level == 10  # essence only
    assert option(7669, items).estimated_level is None  # reagents not fetched


def store(session: Session) -> None:
    for key, payload in RECIPES.items():
        session.add(
            RecipeData(
                recipe_id=int(key),
                profession="Enchanting",
                category=CATEGORY[int(key)],
                payload=payload,
            )
        )
    session.commit()


def test_catalog_leaves_out_season_of_discovery_unless_asked(engine: Engine) -> None:
    with Session(engine) as session:
        store(session)
        default = catalog(session, {})
        everything = catalog(session, {}, include_sod=True)
        ids = reagent_and_crafted_ids(session)
    assert 51763 not in {o.recipe_id for o in default}
    assert len(everything) == len(default) + 1 == 12
    assert {10940, 10938, 10978, 249391} <= set(ids)  # Pyrite (249391) is Forever-new


BASE = "https://us.api.blizzard.com/data/wow"
INDEX = {"professions": [{"name": "Enchanting", "id": 333}, {"name": "Cooking", "id": 185}]}
PROFESSION = {"id": 333, "name": "Enchanting", "skill_tiers": [{"name": "Enchanting", "id": 2940}]}


def blizzard(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/data/wow")
    if path == "/profession/index":
        return httpx.Response(200, json=INDEX)
    if path == "/profession/333":
        return httpx.Response(200, json=PROFESSION)
    if path == "/profession/333/skill-tier/2940":
        return httpx.Response(200, json=TIER)
    if path.startswith("/recipe/") and (body := RECIPES.get(path.removeprefix("/recipe/"))):
        return httpx.Response(200, json=body)
    return httpx.Response(404, text="Not Found")


@respx.mock
def test_refresh_stores_enchant_recipes_and_skips_fresh_ones(
    engine: Engine, settings: Settings
) -> None:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    recipes = respx.get(url__startswith=f"{BASE}/recipe/").mock(side_effect=blizzard)
    respx.get(url__startswith=BASE).mock(side_effect=blizzard)

    with Session(engine) as session, httpx.Client() as http:
        first = refresh_recipes(session, settings, http=http)
        again = refresh_recipes(session, settings, http=http)
        stored = catalog(session, {}, include_sod=True)

    assert first.professions == ["Enchanting"]
    assert first.recipes_listed == 12  # the Reagents category's rod is not an enchant
    assert first.recipes_fetched == 12
    assert first.errors == []
    assert again.recipes_fetched == 0  # cached for 30 days
    assert recipes.call_count == 12
    assert len(stored) == 12
