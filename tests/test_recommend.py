import logging
from pathlib import Path
from typing import Any

import pytest

from character_planner.choices import Choices
from character_planner.curated import GearTarget, GearTargets
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
    # Pickable at 18, but the quest is done inside a 24+ dungeon: the dungeon decides.
    early_pickup = bfd_quest.model_copy(update={"quest_min_level": 18})
    buckler = buckler.model_copy(update={"sources": [early_pickup]})
    assert buckler.effective_level == 24

    drop = PoolSource(kind="drop", dungeon_id="sfk", dungeon="SFK", min_level=20, max_level=30)
    cape = item(21, "Back", required_level=None, sources=[drop], stats={"Stamina": 4})
    assert unusable_reason(cape, RULES, 18) is None  # 20 is within levels_ahead
    back = next(r for r in recommend(view(cape), {}, WEIGHTS, RULES).rows if r.slot == "BACK")
    assert back.candidates[0].usable_now is False


def test_excluded_ids_and_plate_at_forty() -> None:
    assert unusable_reason(item(10, "Back"), RULES, 18, excluded={10}) == "excluded"
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


def test_gains_within_the_sidegrade_band_are_not_listed() -> None:
    pool = view(item(1, "Trinket", stats={"Spirit": 1}), item(2, "Trinket", stats={"Stamina": 1}))
    weights = Weights(weights=WEIGHTS.weights | {"Spirit": 0.05})
    rows = {r.slot: r for r in recommend(pool, {}, weights, RULES).rows}
    assert rows["TRINKET_1"].candidates == []  # +0.05 and +1.0 are both sidegrades
    loose = RULES.model_copy(update={"min_gain": 0.0})
    rows = {r.slot: r for r in recommend(pool, {}, weights, loose).rows}
    assert [c.item.item_id for c in rows["TRINKET_1"].candidates] == [2, 1]


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
    targets = GearTargets(targets=[GearTarget(slot="BACK", item="Drape", source="x", item_id=1)])
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
    assert [(u.item.name, u.slot, u.score_gain) for u in dungeons[0].upgrades] == [
        ("Item 1", "WAIST", 7.0),
        ("Item 2", "BACK", 3.0),
    ]
    assert [u.item.item_id for u in dungeons[1].upgrades] == [3, 5]
    assert dungeons[1].upgrades[0].source.dungeon == "The Deadmines"


def test_rules_file_loads() -> None:
    assert isinstance(RULES, UsageRules)
    assert "Wand" not in RULES.weapon_types
    assert RULES.two_handers is False


def test_dismissed_items_are_never_suggested() -> None:
    deadmines = source("the-deadmines", "The Deadmines")
    pool = view(
        item(1, "Back", stats={"Stamina": 5}),
        item(2, "Back", stats={"Stamina": 3}, sources=[deadmines]),
    )
    recs = recommend(pool, {}, WEIGHTS, RULES, choices=Choices(dismissed={1}))
    back = next(r for r in recs.rows if r.slot == "BACK")
    assert [c.item.item_id for c in back.candidates] == [2]
    assert [d.dungeon for d in recs.dungeons] == ["The Deadmines"]


def targets_for(slot: str, *ids: int, pinned: bool = True) -> GearTargets:
    """Targets for one slot, pinned unless said otherwise."""
    targets = [
        GearTarget(slot=slot, item=f"Item {i}", source="x", item_id=i, pinned=pinned) for i in ids
    ]
    return GearTargets(targets=targets)


def test_pinned_targets_are_always_listed() -> None:
    equipped = {"BACK": worn("BACK", stats=[ItemStat(name="Stamina", value=4)])}
    pool = view(
        item(1, "Back", stats={"Stamina": 9}),
        item(2, "Back", stats={"Stamina": 8}),
        item(3, "Back", stats={"Stamina": 7}),
        item(4, "Back", stats={"Stamina": 6}),  # 4th best: below per_slot
        item(5, "Back", stats={"Stamina": 4}),  # a sidegrade: below min_gain
    )
    targets = targets_for("BACK", 4, 5)
    back = next(
        r for r in recommend(pool, equipped, WEIGHTS, RULES, targets).rows if r.slot == "BACK"
    )
    assert [(c.item.item_id, c.is_target, c.pinned) for c in back.candidates] == [
        (1, False, False),
        (2, False, False),
        (3, False, False),
        (4, True, True),
        (5, True, True),
    ]


def test_targets_that_are_not_pinned_are_only_tagged() -> None:
    pool = view(*(item(i, "Back", stats={"Stamina": 10 - i}) for i in range(1, 6)))
    targets = targets_for("BACK", 2, 5, pinned=False)  # from the YAML
    back = next(r for r in recommend(pool, {}, WEIGHTS, RULES, targets).rows if r.slot == "BACK")
    assert [(c.item.item_id, c.is_target, c.pinned) for c in back.candidates] == [
        (1, False, False),
        (2, True, False),
        (3, False, False),
    ]


def test_pinned_items_already_worn_or_dismissed_are_not_listed() -> None:
    equipped = {"BACK": worn("BACK", item_id=1, stats=[ItemStat(name="Stamina", value=4)])}
    pool = view(item(1, "Back", stats={"Stamina": 4}), item(2, "Back", stats={"Stamina": 2}))
    recs = recommend(
        pool, equipped, WEIGHTS, RULES, targets_for("BACK", 1, 2), Choices(dismissed={2})
    )
    assert next(r for r in recs.rows if r.slot == "BACK").candidates == []


def test_a_pinned_ring_is_listed_in_one_finger_slot() -> None:
    equipped = {"FINGER_1": worn("FINGER_1", stats=[ItemStat(name="Stamina", value=2)])}
    pool = view(item(1, "Finger", stats={"Stamina": 6}), item(2, "Finger", stats={"Stamina": 1}))
    targets = targets_for("FINGER_2", 2)
    rows = {r.slot: r for r in recommend(pool, equipped, WEIGHTS, RULES, targets).rows}
    assert [c.item.item_id for c in rows["FINGER_2"].candidates] == [1, 2]
    assert rows["FINGER_1"].candidates == []


def test_old_exclusions_in_the_yaml_are_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "recommend.yaml"
    path.write_text("weapon_types: [Axe]\narmor_types: [mail]\nexclude_item_ids: [5]\n")
    with caplog.at_level(logging.WARNING):
        rules = load_rules(path)
    assert rules.weapon_types == ["Axe"]
    assert "exclude_item_ids is no longer read" in caplog.text


# A caster's rules, as a Warlock's will be (#80): cloth, staves but no other two-handers,
# held-in-off-hand items, wands.
CASTER = UsageRules(
    weapon_types=["Dagger", "Sword", "Staff", "Wand"],
    armor_types=["cloth"],
    plate_from_level=None,
    two_handers=True,
    two_hand_types=["Staff"],
    off_hand_types=["Miscellaneous"],
)


@pytest.mark.parametrize(
    ("pool_item", "reason"),
    [
        (item(1, "Two-Hand", weapon_type="Staff"), None),
        (item(2, "Two-Hand", weapon_type="Sword"), "no two-handed Sword"),
        (item(3, "One-Hand", weapon_type="Sword"), None),
        (item(4, "Held In Off-hand", weapon_type="Miscellaneous"), None),
        (item(5, "Held In Off-hand", weapon_type=None), None),  # 6 such items in the pool
        (item(6, "Off Hand", weapon_type="Shield"), "can't use Shield"),
        (item(7, "Chest", armor_type="Leather"), "not wearing leather"),
        (item(8, "Chest", armor_type="Mail"), "not wearing mail"),
        (item(9, "Chest", armor_type="Plate"), "plate not yet"),
        (item(10, "Ranged", weapon_type="Wand"), None),
    ],
)
def test_caster_rules(pool_item: PoolItem, reason: str | None) -> None:
    assert unusable_reason(pool_item, CASTER, 18) == reason


def test_mail_from_level_forty() -> None:
    """Hunters and Shamans wear leather until they learn mail at 40."""
    hunter = RULES.model_copy(
        update={
            "armor_types": ["cloth", "leather"],
            "mail_from_level": 40,
            "plate_from_level": None,
        }
    )
    mail = item(1, "Chest", armor_type="Mail", required_level=30)
    assert unusable_reason(mail, hunter, 39) == "mail not yet"
    assert unusable_reason(mail, hunter, 40) is None
    assert unusable_reason(mail, hunter, None) == "mail not yet"


def test_warrior_rules_are_unchanged_by_the_new_fields() -> None:
    assert RULES.mail_from_level is None and RULES.two_hand_types is None
    assert unusable_reason(item(1, "Chest", armor_type="Mail"), RULES, 18) is None
