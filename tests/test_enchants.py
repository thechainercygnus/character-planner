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
    EnchantData,
    EnchantOption,
    Reagent,
    advise,
    catalog,
    enchant_score,
    equipped_effects,
    estimate_level,
    fits,
    load_enchant_data,
    parse_effects,
    parse_recipe,
    reagent_and_crafted_ids,
    refresh_recipes,
)
from character_planner.recommend import load_rules
from character_planner.scoring import load_default_weights
from character_planner.views import Enchantment, EquippedItem, known_recipe_ids, parse_equipment

from .conftest import FIXTURES, REPO_ROOT

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


# --- curated data, crafted items and recommendations (ADR 0010) ------------------------

DATA = load_enchant_data(REPO_ROOT / "data" / "curated" / "enchants.yaml")
WEIGHTS = load_default_weights(REPO_ROOT / "data" / "curated" / "stat_weights.yaml")
RULES = load_rules(REPO_ROOT / "data" / "curated" / "recommend.yaml")
# The real Crude Scope recipe (2421) from the 2026-11-12 refresh: no description, a
# crafted item (4405) and reagents with no level band (tubes, bolts, Malachite).
CRUDE_SCOPE: dict[str, Any] = json.loads(
    (FIXTURES / "blizzard_recipe_crude_scope.json").read_text(encoding="utf-8")
)


def equipment() -> dict[str, EquippedItem]:
    raw = json.loads((FIXTURES / "forever_equipment.json").read_text(encoding="utf-8"))
    return {item.slot: item for item in parse_equipment(raw)}


def known() -> set[int]:
    raw = json.loads((FIXTURES / "forever_professions.json").read_text(encoding="utf-8"))
    return known_recipe_ids(raw)


def scope_option(data: EnchantData = DATA) -> EnchantOption:
    parsed = parse_recipe(CRUDE_SCOPE, "Engineering", "Scopes", {}, data)
    assert parsed is not None
    return parsed


def options() -> list[EnchantOption]:
    """The fixture's enchanting recipes (no Season of Discovery) and the Crude Scope,
    with the curated material bands applied."""
    enchanting = [
        parse_recipe(payload, "Enchanting", CATEGORY[int(key)], {}, DATA)
        for key, payload in RECIPES.items()
    ]
    return [o for o in enchanting if o and not o.season_of_discovery] + [scope_option()]


def test_equipped_stat_enchant_text_is_parsed() -> None:
    # The FEET enchant's display string in the 2026-11-11 equipment sync.
    assert parse_effects("Enchanted: Stamina +3") == {"Stamina": 3}


def test_curated_material_bands_set_the_level_estimate() -> None:
    dust = [Reagent(item_id=10940, name="Strange Dust", quantity=1)]
    companion = {10940: CompanionInfo(item_id=10940, item_level=60)}
    assert estimate_level(dust, companion, DATA.reagent_levels) == 1  # the band wins
    soul = [Reagent(item_id=11083, name="Soul Dust", quantity=1)]
    assert estimate_level(soul, {}, DATA.reagent_levels) == 21
    assert estimate_level(soul, {}) is None


def test_crafted_item_effects_come_from_the_equipment_then_the_curated_list() -> None:
    learned = equipped_effects(equipment().values())
    assert learned == {4405: {WEAPON_DAMAGE: 1}}  # "Enchanted: Scope (+1 Damage)"

    from_gear = parse_recipe(CRUDE_SCOPE, "Engineering", "Scopes", {}, None, learned)
    assert from_gear is not None
    assert (from_gear.effects, from_gear.effects_source) == ({WEAPON_DAMAGE: 1}, "equipped")
    curated = scope_option()
    assert (curated.effects_source, curated.slots, curated.crafted_item_id) == (
        "curated",
        ["RANGED"],
        4405,
    )
    unknown = scope_option(EnchantData())
    assert (unknown.effects, unknown.effects_source) == ({}, None)


def test_known_recipes_come_from_the_professions_snapshot() -> None:
    assert 2421 in known()  # Crude Scope, Engineering
    assert known_recipe_ids(None) == set()


def test_weapon_damage_scores_as_dps_for_the_weapon_speed() -> None:
    # +2 damage on a 2.0 speed weapon is +1 DPS.
    assert enchant_score(WEIGHTS, "MAIN_HAND", {WEAPON_DAMAGE: 2}, 2.0) == WEIGHTS.of("Weapon DPS")
    assert enchant_score(WEIGHTS, "RANGED", {WEAPON_DAMAGE: 2}, 2.0) == WEIGHTS.of("Ranged DPS")
    assert enchant_score(WEIGHTS, "MAIN_HAND", {WEAPON_DAMAGE: 2}, None) == 0
    assert enchant_score(WEIGHTS, "WRIST", {"Stamina": 3, "Defense": 3}, None) == 6.0


def test_fits_checks_shields_two_handers_and_ranged_types() -> None:
    gear = equipment()
    block, impact, striking = option(7528), option(4368), option(4367)
    assert fits(block, "OFF_HAND", gear["OFF_HAND"], RULES)  # Burnished Shield
    orb = gear["OFF_HAND"].model_copy(update={"armor_type": "Miscellaneous"})
    assert not fits(block, "OFF_HAND", orb, RULES)
    # Two-handed enchants need a two-hander in hand (#93): the Thelsamar Axe is one-handed.
    assert gear["MAIN_HAND"].inventory_type == "WEAPONMAINHAND"
    assert not fits(impact, "MAIN_HAND", gear["MAIN_HAND"], RULES)
    assert fits(striking, "MAIN_HAND", gear["MAIN_HAND"], RULES)
    greataxe = gear["MAIN_HAND"].model_copy(update={"inventory_type": "TWOHWEAPON"})
    assert fits(impact, "MAIN_HAND", greataxe, RULES)
    assert fits(striking, "MAIN_HAND", greataxe, RULES)  # one-hand weapon enchants fit too
    no_two_handers = RULES.model_copy(update={"two_handers": False})
    assert not fits(impact, "MAIN_HAND", greataxe, no_two_handers)
    assert fits(scope_option(), "RANGED", gear["RANGED"], RULES)  # Rough Boomstick, a Gun
    thrown = gear["RANGED"].model_copy(update={"armor_type": "Thrown"})
    assert not fits(scope_option(), "RANGED", thrown, RULES)


def test_advice_ranks_enchants_against_the_one_on_now() -> None:
    advice = advise(options(), equipment(), WEIGHTS, RULES, 18, known(), DATA)
    rows = {r.slot: r for r in advice.rows}
    assert list(rows) == ["BACK", "CHEST", "WRIST", "FEET", "MAIN_HAND", "OFF_HAND", "RANGED"]

    chest = rows["CHEST"]  # Minor Stats (+1 all: 2.15) beats Inferior Stamina (+2: 2.0)
    assert [p.option.name for p in chest.picks] == [
        "Enchant Chest - Minor Stats",
        "Enchant Chest - Inferior Stamina",
    ]
    assert chest.current is None and not chest.current_is_weaker

    # The Boomstick already has the Crude Scope: nothing better to list.
    ranged = rows["RANGED"]
    assert ranged.current is not None and ranged.current.effects == {WEAPON_DAMAGE: 1}
    assert ranged.picks == [] and not ranged.current_is_weaker

    # Two-handed Minor Impact never reaches a one-handed tank.
    assert [p.option.name for p in rows["MAIN_HAND"].picks] == ["Enchant Weapon - Minor Striking"]
    # Lesser Block (Vision Dust: 31) and Minor Speed (Lesser Nether Essence: 36) are past
    # level 18 + 3; Recovery is in reach but a proc, with nothing to weigh.
    assert rows["OFF_HAND"].picks == []
    assert advice.unscored == 1
    assert advice.recipes == 12


def test_advice_flags_a_weaker_enchant_and_makeable_recipes() -> None:
    gear = equipment()
    gear["FEET"] = gear["FEET"].model_copy(
        update={"enchantments": [Enchantment(text="Enchanted: Stamina +1", kind="PERMANENT")]}
    )
    advice = advise(options(), gear, WEIGHTS, RULES, 18, known(), DATA)
    feet = next(r for r in advice.rows if r.slot == "FEET")
    assert feet.current is not None and feet.current.score == 1.0
    assert feet.current_is_weaker
    assert [(p.option.name, p.score_gain, p.can_make) for p in feet.picks] == [
        ("Enchant Boots - Minor Stamina", 2.0, False)
    ]


def test_advice_gates_by_the_level_estimate_unless_the_recipe_is_known() -> None:
    too_high = option(4293).model_copy(update={"estimated_level": 30})
    no_estimate = option(4402).model_copy(update={"estimated_level": None})
    scope = scope_option().model_copy(update={"estimated_level": None})
    gear = equipment()
    gear["RANGED"] = gear["RANGED"].model_copy(update={"enchantments": []})
    advice = advise([too_high, no_estimate, scope], gear, WEIGHTS, RULES, 18, known(), DATA)
    rows = {r.slot: r for r in advice.rows}
    assert rows["WRIST"].picks == []  # 30 is past level 18 + 3 levels ahead
    assert rows["FEET"].picks == [] and advice.unknown_level == 1
    picked = rows["RANGED"].picks[0]  # no estimate, but Engineering knows the recipe
    assert (picked.option.name, picked.can_make, picked.usable_now) == ("Crude Scope", True, True)


def test_empty_slots_are_listed_without_picks() -> None:
    gear = equipment()
    del gear["BACK"]
    advice = advise(options(), gear, WEIGHTS, RULES, 18, known(), DATA)
    back = next(r for r in advice.rows if r.slot == "BACK")
    assert (back.item, back.picks) == (None, [])
