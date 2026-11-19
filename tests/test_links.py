"""Wowhead links (#225): every view model that names an item links it when the id is known."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.choices import ItemChoiceView
from character_planner.companion import parse_item
from character_planner.crafting import CraftedItem
from character_planner.curated import GearTarget, GearTargets
from character_planner.db import StoredGearTargets, owned
from character_planner.enchants import EnchantData, MissingEffect, advise, parse_recipe
from character_planner.guild import MemberNeed
from character_planner.links import item_url, quest_url
from character_planner.lookahead import target_events
from character_planner.pool import PoolItem, PoolSource
from character_planner.recommend import load_rules
from character_planner.scoring import load_default_weights
from character_planner.targets import save_targets
from character_planner.views import (
    GearPlan,
    SlotOutlook,
    UpcomingTarget,
    parse_equipment,
    target_info,
)

from .conftest import FIXTURES, REPO_ROOT, tracked

GIRDLE = "https://www.wowhead.com/forever/item=270230"
RULES = load_rules(REPO_ROOT / "data" / "curated" / "recommend.yaml")
WEIGHTS = load_default_weights(REPO_ROOT / "data" / "curated" / "stat_weights.yaml")


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_a_link_is_the_sources_own_else_built_from_the_id() -> None:
    assert item_url(270230) == GIRDLE
    assert item_url(270230, "https://example.test/given") == "https://example.test/given"
    assert item_url(None) is None
    assert quest_url(1640) == "https://www.wowhead.com/forever/quest=1640"
    assert quest_url(None) is None


def test_pool_items_link_even_when_their_source_gave_none() -> None:
    source = PoolSource(kind="drop", dungeon="X")
    assert PoolItem(item_id=2589, name="Linen Cloth", sources=[source]).wowhead == (
        "https://www.wowhead.com/forever/item=2589"
    )
    given = PoolItem(item_id=1, name="Given", sources=[source], wowhead="https://example.test/1")
    assert given.wowhead == "https://example.test/1"
    # Through the pool's own cache (a dict), too.
    assert PoolItem.model_validate(given.model_dump()).wowhead == "https://example.test/1"


def test_companion_items_keep_their_link_or_get_one() -> None:
    info = parse_item(fixture("companion_item_270230.json"))
    assert info is not None and info.wowhead == GIRDLE
    payload = {**fixture("companion_item_270230.json"), "wowhead": None}
    bare = parse_item(payload)
    assert bare is not None and bare.wowhead == GIRDLE


def test_equipped_items_and_the_item_behind_an_enchant_link() -> None:
    equipment = parse_equipment(fixture("forever_equipment.json"))
    assert equipment
    for item in equipment:
        assert item.item_id is not None
        assert item.wowhead == f"https://www.wowhead.com/forever/item={item.item_id}"
        dumped = item.model_dump()
        assert dumped["wowhead"] == item.wowhead  # in the API's JSON
    enchants = [e for item in equipment for e in item.enchantments]
    scoped = [e for e in enchants if e.source_item_id is not None]
    assert scoped and all(e.wowhead == item_url(e.source_item_id) for e in scoped)
    assert all(e.wowhead is None for e in enchants if e.source_item_id is None)


def test_targets_link_from_their_id_but_the_link_is_never_saved(engine: Engine) -> None:
    target = GearTarget(slot="WAIST", item="Kindlegem Girdle", source="x", item_id=270230)
    assert target.wowhead == GIRDLE
    assert GearTarget(slot="WAIST", item="Unknown", source="x").wowhead is None

    with Session(engine) as session:
        character_id = tracked(session)
        save_targets(session, GearTargets(targets=[target]), character_id)
        row = owned(session, StoredGearTargets, character_id)
        assert row is not None
        assert all("wowhead" not in t for t in row.targets["targets"])


def test_target_info_links_without_a_companion_link() -> None:
    target = GearTarget(
        slot="WAIST", item="Kindlegem Girdle", source="x", item_id=270230, item_level=20
    )
    info = target_info(target, {}, {})
    assert info is not None and info.wowhead == GIRDLE


def test_enchant_options_reagents_and_missing_effects_link() -> None:
    scope = parse_recipe(fixture("blizzard_recipe_crude_scope.json"), "Engineering", "Scopes", {})
    assert scope is not None and scope.crafted_item_id is not None
    assert scope.wowhead == item_url(scope.crafted_item_id)  # the scope itself
    assert scope.reagents
    assert all(r.wowhead == item_url(r.item_id) for r in scope.reagents)
    missing = MissingEffect(item_id=4405, recipe="Crude Scope", slots=["RANGED"])
    assert missing.wowhead == "https://www.wowhead.com/forever/item=4405"

    # A plain enchant (no crafted item) has no page we know: recipe ids aren't spell ids.
    recipes = fixture("blizzard_recipes_enchanting.json")
    plain = next(
        option
        for payload in recipes.values()
        if (option := parse_recipe(payload, "Enchanting", "Bracer", {})) is not None
        and option.crafted_item_id is None
    )
    assert plain.wowhead is None
    assert all(r.wowhead for r in plain.reagents)


def test_guild_needs_choices_and_crafted_items_link() -> None:
    need = MemberNeed(item="Robe", item_id=6542, slot="CHEST", score_gain=3)
    assert need.wowhead == "https://www.wowhead.com/forever/item=6542"
    choice = ItemChoiceView(
        item_id=5193, name="Cape", choice="dismissed", created_at=datetime.now(UTC)
    )
    assert choice.wowhead == "https://www.wowhead.com/forever/item=5193"
    info = parse_item(fixture("companion_item_270230.json"))
    assert info is not None
    crafted = CraftedItem(
        item_id=270230, name="Girdle", profession="Leatherworking", recipe="x", info=info
    )
    assert crafted.info.wowhead == GIRDLE


def test_enchant_rows_link_the_worn_item() -> None:
    worn = {item.slot: item for item in parse_equipment(fixture("forever_equipment.json"))}
    advice = advise([], worn, WEIGHTS, RULES, 18, set(), EnchantData())
    assert advice.rows
    for row in advice.rows:
        assert row.wowhead == worn[row.slot].wowhead


def test_look_ahead_links_a_target_with_no_item_details_yet() -> None:
    target = GearTarget(slot="BACK", item="Cape", source="Vendor", item_id=5193)
    later = UpcomingTarget(target=target, target_info=None, level=20)
    plan = GearPlan(
        level=18, rows=[], later=[SlotOutlook(slot="BACK", equipped=None, upcoming=[later])]
    )
    ((_, event),) = target_events(plan, 18, 21)
    assert event.link == "https://www.wowhead.com/forever/item=5193"
