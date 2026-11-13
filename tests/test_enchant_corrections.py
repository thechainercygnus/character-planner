"""Corrections to the enchant reference data, made in the app (#36, ADR 0033)."""

import json

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.db import RecipeData
from character_planner.enchant_corrections import EnchantCorrections, apply
from character_planner.enchants import (
    EnchantData,
    advise,
    load_enchant_data,
    parse_recipe,
)
from character_planner.recommend import load_rules
from character_planner.scoring import load_default_weights
from character_planner.views import parse_equipment

from .conftest import FIXTURES, REPO_ROOT
from .test_app import client, fixture  # noqa: F401 (the client fixture)
from .test_enchants import CATEGORY, RECIPES
from .test_enchants import store as store_recipes

SHIPPED = load_enchant_data(REPO_ROOT / "data" / "curated" / "enchants.yaml")
# Real recipe: Crude Scope makes item 4405; its reagents have no shipped band.
SCOPE = json.loads((FIXTURES / "blizzard_recipe_crude_scope.json").read_text(encoding="utf-8"))
STRANGE_DUST, LESSER_MAGIC, SMALL_SHARD = 10940, 10938, 10978


def test_corrections_go_on_top_of_the_shipped_data() -> None:
    corrections = EnchantCorrections(
        reagent_levels={STRANGE_DUST: 8}, crafted_effects={9999: {"Stamina": 3}}, per_slot=5
    )
    data = apply(SHIPPED, corrections)
    assert data.reagent_levels[STRANGE_DUST] == 8
    assert data.reagent_levels[SMALL_SHARD] == SHIPPED.reagent_levels[SMALL_SHARD]
    assert data.crafted_effects[4405] == SHIPPED.crafted_effects[4405]  # shipped, untouched
    assert data.crafted_effects[9999] == {"Stamina": 3}
    assert (data.per_slot, data.per_slot_corrected) == (5, True)
    assert (data.corrected_reagents, data.corrected_crafted) == ({STRANGE_DUST}, {9999})
    untouched = apply(SHIPPED, EnchantCorrections())
    assert (untouched.per_slot, untouched.per_slot_corrected) == (SHIPPED.per_slot, False)


def test_a_newer_shipped_file_still_reaches_what_isnt_corrected() -> None:
    corrections = EnchantCorrections(reagent_levels={STRANGE_DUST: 8})
    # A release improves both bands; only the uncorrected one changes.
    newer = SHIPPED.model_copy(
        update={"reagent_levels": {**SHIPPED.reagent_levels, STRANGE_DUST: 2, SMALL_SHARD: 14}}
    )
    data = apply(newer, corrections)
    assert data.reagent_levels[STRANGE_DUST] == 8  # the correction holds
    assert data.reagent_levels[SMALL_SHARD] == 14  # the new shipped band arrives


def test_each_material_says_where_its_level_comes_from() -> None:
    data = apply(SHIPPED, EnchantCorrections(reagent_levels={LESSER_MAGIC: 12}))
    # Minor Striking: Strange Dust (shipped 1), Lesser Magic Essence (corrected to 12) and
    # Small Glimmering Shard (shipped 11).
    striking = parse_recipe(RECIPES["4367"], "Enchanting", CATEGORY[4367], {}, data)
    assert striking is not None
    levels = {(r.name, r.level, r.level_source) for r in striking.reagents}
    assert levels == {
        ("Strange Dust", 1, "shipped"),
        ("Lesser Magic Essence", 12, "corrected"),
        ("Small Glimmering Shard", 11, "shipped"),
    }
    assert striking.estimated_level == 12
    # Crude Scope's materials have no band and no Forever Companion level.
    scope = parse_recipe(SCOPE, "Engineering", "Scopes", {}, data)
    assert scope is not None
    assert {r.level_source for r in scope.reagents} == {None}


def test_a_corrected_crafted_effect_is_marked() -> None:
    data = apply(SHIPPED, EnchantCorrections(crafted_effects={4405: {"Weapon Damage": 2}}))
    scope = parse_recipe(SCOPE, "Engineering", "Scopes", {}, data)
    assert scope is not None
    assert (scope.effects, scope.effects_source) == ({"Weapon Damage": 2}, "corrected")
    shipped = parse_recipe(SCOPE, "Engineering", "Scopes", {}, SHIPPED)
    assert shipped is not None
    assert (shipped.effects, shipped.effects_source) == ({"Weapon Damage": 1}, "curated")


def test_scopes_without_a_known_effect_are_listed_to_fill_in() -> None:
    no_scope_effect = SHIPPED.model_copy(update={"crafted_effects": {}})
    scope = parse_recipe(SCOPE, "Engineering", "Scopes", {}, no_scope_effect)
    assert scope is not None
    equipped = {i.slot: i for i in parse_equipment(fixture("equipment"))}
    advice = advise(
        [scope],
        equipped,
        load_default_weights(REPO_ROOT / "data" / "curated" / "stat_weights.yaml"),
        load_rules(REPO_ROOT / "data" / "curated" / "recommend.yaml"),
        18,
        {2421},  # the character knows Crude Scope
        no_scope_effect,
    )
    assert [(m.item_id, m.recipe, m.slots) for m in advice.missing_effects] == [
        (4405, "Crude Scope", ["RANGED"])
    ]
    assert (advice.per_slot, advice.per_slot_corrected) == (3, False)


def test_corrections_through_the_api(client: TestClient, engine: Engine) -> None:  # noqa: F811
    empty = client.get("/api/enchants/corrections").json()
    assert empty["corrections"] == {"reagent_levels": {}, "crafted_effects": {}, "per_slot": None}
    assert empty["shipped"]["per_slot"] == 3
    assert "Weapon Damage" in empty["effect_names"]
    with Session(engine) as session:
        store_recipes(session)
        assert session.get(RecipeData, 4367) is not None

    def striking() -> dict:
        options = client.get("/api/enchants").json()
        return next(o for o in options if o["recipe_id"] == 4367)

    assert striking()["estimated_level"] == 11
    put = client.put(f"/api/enchants/corrections/materials/{LESSER_MAGIC}", json={"level": 14})
    assert put.status_code == 200
    assert put.json()["corrections"]["reagent_levels"] == {str(LESSER_MAGIC): 14}
    corrected = striking()
    assert corrected["estimated_level"] == 14
    essence = next(r for r in corrected["reagents"] if r["item_id"] == LESSER_MAGIC)
    assert (essence["level"], essence["level_source"]) == (14, "corrected")

    reset = client.delete(f"/api/enchants/corrections/materials/{LESSER_MAGIC}")
    assert reset.json()["corrections"]["reagent_levels"] == {}
    assert striking()["estimated_level"] == 11
    assert client.delete(f"/api/enchants/corrections/materials/{LESSER_MAGIC}").status_code == 404

    effect = client.put(
        "/api/enchants/corrections/crafted/4405", json={"effects": {"Weapon Damage": 2}}
    )
    assert effect.json()["corrections"]["crafted_effects"] == {"4405": {"Weapon Damage": 2.0}}
    bad_name = client.put("/api/enchants/corrections/crafted/4405", json={"effects": {"Luck": 1}})
    assert (bad_name.status_code, bad_name.json()["detail"]) == (400, "Unknown effect: Luck")
    zero = client.put("/api/enchants/corrections/crafted/4405", json={"effects": {"Armor": 0}})
    assert zero.status_code == 400
    assert (
        client.put("/api/enchants/corrections/crafted/4405", json={"effects": {}}).status_code
        == 422
    )
    assert client.delete("/api/enchants/corrections/crafted/4405").status_code == 200

    client.post("/api/snapshots/manual", json={"kind": "profile", "payload": fixture("profile")})
    client.post(
        "/api/snapshots/manual", json={"kind": "equipment", "payload": fixture("equipment")}
    )
    assert client.put("/api/enchants/corrections/per-slot", json={"per_slot": 1}).status_code == 200
    advice = client.get("/api/enchants/recommendations").json()
    assert (advice["per_slot"], advice["per_slot_corrected"]) == (1, True)
    assert all(len(row["picks"]) <= 1 for row in advice["rows"])
    assert client.delete("/api/enchants/corrections/per-slot").status_code == 200
    assert client.get("/api/enchants/recommendations").json()["per_slot"] == 3
    assert client.delete("/api/enchants/corrections/per-slot").status_code == 404

    for path, body in [
        (f"materials/{LESSER_MAGIC}", {"level": 0}),
        (f"materials/{LESSER_MAGIC}", {"level": 61}),
        ("per-slot", {"per_slot": 11}),
    ]:
        assert client.put(f"/api/enchants/corrections/{path}", json=body).status_code == 422


def test_corrections_never_change_the_shipped_view(client: TestClient) -> None:  # noqa: F811
    client.put(f"/api/enchants/corrections/materials/{STRANGE_DUST}", json={"level": 9})
    view = client.get("/api/enchants/corrections").json()
    assert view["shipped"]["reagent_levels"][str(STRANGE_DUST)] == 1
    assert view["corrections"]["reagent_levels"][str(STRANGE_DUST)] == 9


def test_enchant_data_defaults() -> None:
    assert EnchantData().per_slot == 3
