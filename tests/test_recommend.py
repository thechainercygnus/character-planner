from typing import Any

import pytest

from character_planner.curated import Bracket, GearTarget, GearTargets
from character_planner.pool import PoolItem, PoolSource, PoolView
from character_planner.recommend import (
    EQUIPMENT_SLOTS,
    UsageRules,
    load_rules,
    recommend,
    unusable_reason,
)
from character_planner.scoring import Weights
from character_planner.views import EquippedItem, ItemStat

from .conftest import REPO_ROOT

RULES = load_rules(REPO_ROOT / "data" / "curated" / "recommend.yaml")
WEIGHTS = Weights(weights={"Stamina": 1.0, "Armor": 0.1, "Strength": 0.5, "Weapon DPS": 1.5})


def source(dungeon: str = "hall-of-thanes", name: str = "Hall of Thanes") -> PoolSource:
    return PoolSource(
        kind="drop", dungeon_id=dungeon, dungeon=name, min_level=13, max_level=18, detail="Boss"
    )


def item(item_id: int, item_slot: str | None, **fields: Any) -> PoolItem:
    defaults: dict[str, Any] = {
        "name": f"Item {item_id}",
        "required_level": 15,
        "sources": [source()],
    }
    return PoolItem(item_id=item_id, item_slot=item_slot, **(defaults | fields))


def worn(slot: str, **fields: Any) -> EquippedItem:
    return EquippedItem(slot=slot, name=f"Worn {slot}", **fields)


def view(*items: PoolItem, level: int = 18) -> PoolView:
    return PoolView(level=level, faction="alliance", window=(15, 28), items=list(items))


@pytest.mark.parametrize(
    ("pool_item", "reason"),
    [
        (item(1, "Ranged", weapon_type="Wand"), "can't use Wand"),
        (item(2, "Two-Hand", weapon_type="Axe"), "two-hander"),
        (item(3, "Held In Off-hand", weapon_type="Miscellaneous"), "off hand type"),
        (item(4, "Chest", armor_type="Plate"), "plate not yet"),
        (item(5, "Waist", armor_type="Mail", required_level=22), "requires level 22"),
        (item(6, None), "not equippable"),
        (item(7, "Ammo"), "not equippable"),
    ],
)
def test_unusable_items(pool_item: PoolItem, reason: str) -> None:
    assert unusable_reason(pool_item, RULES, 18) == reason


@pytest.mark.parametrize(
    "pool_item",
    [
        item(10, "Off Hand", weapon_type="Shield"),
        item(11, "One-Hand", weapon_type="Dagger"),
        item(12, "Finger", weapon_type="Miscellaneous"),
        item(13, "Back"),
        item(14, "Legs", armor_type="Leather", required_level=21),  # within levels_ahead
    ],
)
def test_usable_items(pool_item: PoolItem) -> None:
    assert unusable_reason(pool_item, RULES, 18) is None


def test_items_without_a_required_level_use_their_quest_or_dungeon_level() -> None:
    bfd_quest = PoolSource(
        kind="quest",
        dungeon_id="blackfathom-deeps",
        dungeon="Blackfathom Deeps",
        min_level=24,
        max_level=32,
        detail="Blackfathom Villainy",
        quest_min_level=27,
    )
    buckler = item(20, "Off Hand", weapon_type="Shield", required_level=None, sources=[bfd_quest])
    assert buckler.effective_level == 27
    assert unusable_reason(buckler, RULES, 18) == "requires level 27"

    drop = PoolSource(kind="drop", dungeon_id="sfk", dungeon="SFK", min_level=20, max_level=30)
    cape = item(21, "Back", required_level=None, sources=[drop], stats={"Stamina": 4})
    assert unusable_reason(cape, RULES, 18) is None  # 20 is within levels_ahead
    back = next(r for r in recommend(view(cape), {}, WEIGHTS, RULES).rows if r.slot == "BACK")
    assert back.candidates[0].usable_now is False


def test_excluded_ids_and_plate_at_forty() -> None:
    rules = RULES.model_copy(update={"exclude_item_ids": [10]})
    assert unusable_reason(item(10, "Back"), rules, 18) == "excluded"
    assert (
        unusable_reason(item(4, "Chest", armor_type="Plate", required_level=40), RULES, 40) is None
    )


def test_ranks_upgrades_per_slot_by_score_gain() -> None:
    belt = worn("WAIST", armor=73, item_level=14)
    pool = view(
        item(1, "Waist", armor=100, stats={"Stamina": 7}, item_level=18),  # +9.7
        item(2, "Waist", armor=90, stats={"Strength": 4}),  # +3.7
        item(3, "Waist", armor=60),  # -1.3: not an upgrade
        item(4, "Waist", required_level=20, armor=80, stats={"Stamina": 20}),  # +20.7, level 20
    )
    result = recommend(pool, {"WAIST": belt}, WEIGHTS, RULES)

    assert [row.slot for row in result.rows] == EQUIPMENT_SLOTS
    waist = next(row for row in result.rows if row.slot == "WAIST")
    assert [(c.item.item_id, c.score_gain) for c in waist.candidates] == [
        (4, 20.7),
        (1, 9.7),
        (2, 3.7),
    ]
    top, kindlegem = waist.candidates[:2]
    assert top.usable_now is False  # requires 20, within levels_ahead
    assert (kindlegem.armor_delta, kindlegem.stat_deltas) == (27, {"Stamina": 7})
    assert kindlegem.item_level_delta == 4
    assert result.considered == 4


def test_empty_slot_takes_any_scored_item_and_counts_unscored() -> None:
    pool = view(item(1, "Neck", stats={"Stamina": 3}), item(2, "Neck"))
    result = recommend(pool, {}, WEIGHTS, RULES)
    neck = next(row for row in result.rows if row.slot == "NECK")
    assert neck.equipped is None
    assert [c.item.item_id for c in neck.candidates] == [1]
    assert (result.considered, result.unscored) == (1, 1)


def test_rings_fill_the_weaker_slot_first_without_repeating_its_pick() -> None:
    equipped = {"FINGER_1": worn("FINGER_1", stats=[ItemStat(name="Stamina", value=2)])}
    pool = view(
        item(1, "Finger", stats={"Stamina": 6}),
        item(2, "Finger", stats={"Stamina": 4}),
    )
    rows = {r.slot: r for r in recommend(pool, equipped, WEIGHTS, RULES).rows}
    # FINGER_2 is empty, so weaker: it gets the best ring; FINGER_1 gets the next one.
    assert [c.item.item_id for c in rows["FINGER_2"].candidates] == [1, 2]
    assert [c.item.item_id for c in rows["FINGER_1"].candidates] == [2]
    assert rows["FINGER_1"].candidates[0].score_gain == 2.0


def test_marks_gear_targets() -> None:
    targets = GearTargets(
        brackets=[
            Bracket(
                min_level=15,
                targets=[GearTarget(slot="BACK", item="Drape", source="x", item_id=1)],
            )
        ]
    )
    pool = view(item(1, "Back", stats={"Stamina": 3}), item(2, "Back", stats={"Stamina": 2}))
    back = next(r for r in recommend(pool, {}, WEIGHTS, RULES, targets).rows if r.slot == "BACK")
    assert [c.is_target for c in back.candidates] == [True, False]


def test_ranks_dungeons_by_usable_upgrades() -> None:
    deadmines = source("the-deadmines", "The Deadmines")
    pool = view(
        item(1, "Waist", stats={"Stamina": 7}),  # HoT +7
        item(2, "Back", stats={"Stamina": 3}),  # HoT +3
        item(3, "Waist", stats={"Stamina": 5}, sources=[deadmines]),  # Deadmines +5
        item(4, "Back", stats={"Stamina": 9}, sources=[deadmines], required_level=20),  # later
        item(5, "Finger", stats={"Stamina": 4}, sources=[deadmines]),  # both ring slots: once
    )
    dungeons = recommend(pool, {}, WEIGHTS, RULES).dungeons
    assert [(d.dungeon, d.total_gain) for d in dungeons] == [
        ("Hall of Thanes", 10.0),
        ("The Deadmines", 9.0),  # the level-20 cape doesn't count yet; the ring counts once
    ]
    assert dungeons[0].upgrades == ["Item 1 (+7)", "Item 2 (+3)"]
    assert dungeons[1].upgrades == ["Item 3 (+5)", "Item 5 (+4)"]


def test_rules_file_loads() -> None:
    assert isinstance(RULES, UsageRules)
    assert "Wand" not in RULES.weapon_types
    assert RULES.two_handers is False
