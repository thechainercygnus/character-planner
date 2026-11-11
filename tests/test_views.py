import json
from typing import Any

from character_planner.companion import CompanionInfo
from character_planner.curated import Bracket, GearTarget, GearTargets
from character_planner.db import CatalogItem, Snapshot
from character_planner.scoring import Weights
from character_planner.views import (
    character_view,
    gear_plan,
    parse_equipment,
    parse_professions,
    parse_specialization,
    parse_stats,
)

from .conftest import FIXTURES


def payload(kind: str) -> Any:
    return json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))


def test_parse_equipment_reads_item_details() -> None:
    items = {item.slot: item for item in parse_equipment(payload("equipment"))}
    shield = items["OFF_HAND"]
    assert shield.name == "Burnished Shield"
    assert shield.item_id == 3655
    assert shield.quality == "UNCOMMON"
    assert shield.armor == 428
    assert {s.name: s.value for s in shield.stats} == {"Strength": 2, "Stamina": 3}


def test_parse_stats() -> None:
    stats = parse_stats(payload("statistics"))
    assert stats is not None
    assert stats.armor == 1105
    assert stats.defense == 91
    assert stats.block == 10.04


def test_parse_professions_keeps_primary_flag() -> None:
    professions = {p.name: p for p in parse_professions(payload("professions"))}
    assert professions["Mining"].skill == 108
    assert professions["Mining"].max_skill == 150
    assert professions["Mining"].primary is True
    assert professions["First Aid"].primary is False


def test_parse_specialization() -> None:
    spec = parse_specialization(payload("specializations"))
    assert spec is not None
    assert spec.name == "Protection"
    assert spec.spent_points == 9
    assert {t.name: t.rank for t in spec.talents}["Shield Specialization"] == 5


def test_parsers_tolerate_garbage() -> None:
    assert parse_equipment("Not Found") == []
    assert parse_stats(None) is None
    assert parse_professions({"primaries": [{}]}) == []
    assert parse_specialization({}) is None


def test_character_view_combines_snapshots() -> None:
    latest = {
        kind: Snapshot(source="api", kind=kind, status=200, payload=payload(kind))
        for kind in ("profile", "statistics", "professions", "specializations", "equipment")
    }
    view = character_view(latest)
    assert (view.name, view.surname, view.level) == ("Brumboldt", "Doomlet", 18)
    assert view.race == "Gnome"
    assert view.character_class == "Warrior"
    assert len(view.equipment) == 14
    # 12 gear pieces (shirt and ammo don't count), 175 item levels: 14.6. The API's own
    # equipped_item_level (9) counts empty slots.
    assert (view.equipped_item_level, view.gear_slots_filled) == (14.6, 12)


# --- gear verdicts ------------------------------------------------------------------------


def _latest() -> dict[str, Snapshot]:
    return {
        kind: Snapshot(source="api", kind=kind, status=200, payload=payload(kind))
        for kind in ("profile", "equipment")
    }


def _targets(*targets: GearTarget) -> GearTargets:
    return GearTargets(brackets=[Bracket(min_level=15, targets=list(targets))])


def _catalog(name: str, data: dict[str, Any] | None) -> dict[str, CatalogItem]:
    return {
        name.casefold(): CatalogItem(
            name_key=name.casefold(),
            name=name,
            found=data is not None,
            item_id=data.get("id") if data else None,
            payload=data,
        )
    }


def test_api_item_level_lower_than_equipped_is_a_downgrade() -> None:
    target = GearTarget(slot="OFF_HAND", item="Dwarven Defender", source="Quest")
    search = payload("item_search_dwarven_defender")
    data = next(r["data"] for r in search["results"] if r["data"]["id"] == 6187)

    row = gear_plan(_latest(), _targets(target), _catalog("Dwarven Defender", data)).rows[0]

    assert row.target_info is not None and row.target_info.sources == ["blizzard"]
    assert row.target_info.armor_type == "Shield"
    assert (row.verdict, row.item_level_delta) == ("downgrade", -4)


def test_manual_data_fills_in_items_the_search_cannot_find() -> None:
    target = GearTarget(
        slot="WAIST",
        item="Kindlegem Girdle",
        source="Hall of Thanes",
        item_level=22,
        armor_type="Mail",
    )
    row = gear_plan(_latest(), _targets(target), _catalog("Kindlegem Girdle", None)).rows[0]

    assert row.target_info is not None and row.target_info.sources == ["manual"]
    assert (row.verdict, row.item_level_delta) == ("upgrade", 8)  # equipped belt is ilvl 14
    assert row.warning is None


def test_lighter_armor_target_gets_a_warning() -> None:
    target = GearTarget(
        slot="LEGS",
        item="Direhammer Leggings",
        source="Hall of Thanes",
        item_level=14,
        armor_type="Leather",
    )
    row = gear_plan(_latest(), _targets(target)).rows[0]

    assert row.verdict == "sidegrade"  # equipped Stormwind Guard Leggings are ilvl 13
    assert row.warning == "Leather replacing Mail"


def test_unknown_without_any_item_data() -> None:
    target = GearTarget(slot="HANDS", item="Flamefist Grips", source="Hall of Thanes")
    row = gear_plan(_latest(), _targets(target)).rows[0]
    assert (row.target_info, row.verdict) == (None, "unknown")


def test_equipping_the_target_marks_it_reached() -> None:
    target = GearTarget(slot="OFF_HAND", item="Burnished Shield", source="Vendor")
    row = gear_plan(_latest(), _targets(target)).rows[0]
    assert (row.reached, row.verdict) == (True, "reached")


def test_empty_slot_with_known_target_is_an_upgrade() -> None:
    target = GearTarget(slot="NECK", item="Tarnished Locket", source="Quest", item_level=20)
    row = gear_plan(_latest(), _targets(target)).rows[0]
    assert row.equipped is None
    assert row.verdict == "upgrade"


# --- merging sources ------------------------------------------------------------------------


def _companion(**overrides: Any) -> dict[int, CompanionInfo]:
    info = CompanionInfo(
        item_id=270230,
        item_level=18,
        armor_type="Mail",
        armor=100,
        stats={"Stamina": 7},
        drops=["Hall of Thanes - Magmatus"],
        verified=3,
    ).model_copy(update=overrides)
    return {info.item_id: info}


def test_companion_fills_in_items_blizzard_cannot_see() -> None:
    target = GearTarget(slot="WAIST", item="Kindlegem Girdle", source="?", item_id=270230)
    row = gear_plan(_latest(), _targets(target), companion=_companion()).rows[0]

    assert row.target_info is not None
    assert row.target_info.sources == ["companion"]
    assert row.target_info.drops == ["Hall of Thanes - Magmatus"]
    assert (row.verdict, row.item_level_delta) == ("upgrade", 4)
    assert row.armor_delta == 27  # Belt of the People's Militia has 73 armor
    assert row.stat_deltas == {"Stamina": 7}


def test_stat_deltas_subtract_what_the_equipped_item_gives() -> None:
    # Equipped Stormwind Guard Leggings: 113 armor, +3 Strength.
    target = GearTarget(slot="LEGS", item="Test Legs", source="?", item_id=270230)
    companion = _companion(armor=130, stats={"Stamina": 4})
    row = gear_plan(_latest(), _targets(target), companion=companion).rows[0]

    assert row.armor_delta == 17
    assert row.stat_deltas == {"Stamina": 4, "Strength": -3}


def test_manual_overrides_and_blizzard_beats_companion_with_conflict_noted() -> None:
    target = GearTarget(slot="OFF_HAND", item="Dwarven Defender", source="?", armor=500)
    search = payload("item_search_dwarven_defender")
    data = next(r["data"] for r in search["results"] if r["data"]["id"] == 6187)
    companion = {6187: CompanionInfo(item_id=6187, item_level=19, armor=600, stats={})}

    info = (
        gear_plan(
            _latest(), _targets(target), _catalog("Dwarven Defender", data), companion=companion
        )
        .rows[0]
        .target_info
    )

    assert info is not None
    assert info.sources == ["blizzard", "companion", "manual"]
    assert info.item_level == 17  # Blizzard over Companion
    assert info.armor == 500  # manual over Companion
    assert info.conflicts == ["item level: Blizzard 17, Forever Companion 19"]


def test_attribution_only_when_companion_data_is_used() -> None:
    target = GearTarget(slot="WAIST", item="Kindlegem Girdle", source="?", item_id=270230)
    with_companion = gear_plan(_latest(), _targets(target), companion=_companion())
    without = gear_plan(_latest(), _targets(target))
    assert with_companion.attributions[0]["url"] == "https://forevercompanion.io"
    assert without.attributions == []


# --- scoring --------------------------------------------------------------------------------

WEIGHTS = Weights(
    weights={"Stamina": 1.0, "Armor": 0.1, "Agility": 0.6, "Strength": 0.5, "Weapon DPS": 1.5}
)


def test_weapon_score_counts_dps() -> None:
    # Equipped Thelsamar Axe: 9.05 DPS, +2 Agility -> 13.57 + 1.2 = 14.77
    axe = CompanionInfo(item_id=270256, item_level=18, dps=12.3, stats={"Strength": 4})
    target = GearTarget(slot="MAIN_HAND", item="Durgen's Crescent Axe", source="?", item_id=270256)
    row = gear_plan(_latest(), _targets(target), companion={270256: axe}, weights=WEIGHTS).rows[0]

    assert row.score_delta == 5.68  # 20.45 - 14.77
    assert (row.verdict, row.verdict_basis) == ("upgrade", "score")


def test_score_overrules_item_level() -> None:
    # Same item level, but the target is leather with less armor: a score downgrade.
    legs = CompanionInfo(
        item_id=1, item_level=18, armor_type="Leather", armor=72, stats={"Agility": 4}
    )
    target = GearTarget(slot="LEGS", item="Direhammer Leggings", source="?", item_id=1)
    row = gear_plan(_latest(), _targets(target), companion={1: legs}, weights=WEIGHTS).rows[0]

    # target 7.2 + 2.4 = 9.6; equipped 11.3 + 1.5 = 12.8
    assert row.score_delta == -3.2
    assert (row.verdict, row.verdict_basis) == ("downgrade", "score")
    assert row.item_level_delta == 5  # still reported


def test_rows_sort_by_score_gain_then_priority() -> None:
    companion = {
        1: CompanionInfo(item_id=1, armor=100, stats={"Stamina": 7}),  # waist: +9.7
        2: CompanionInfo(item_id=2, armor=200, stats={}),  # feet: 20 - 12.9 = +7.1
    }
    targets = _targets(
        GearTarget(slot="HANDS", item="No Data Gloves", source="?", priority=1),
        GearTarget(slot="FEET", item="Feet", source="?", item_id=2, priority=2),
        GearTarget(slot="WAIST", item="Belt", source="?", item_id=1, priority=3),
    )
    rows = gear_plan(_latest(), targets, companion=companion, weights=WEIGHTS).rows
    assert [r.slot for r in rows] == ["WAIST", "FEET", "HANDS"]


def test_without_weights_verdicts_use_item_level() -> None:
    target = GearTarget(slot="WAIST", item="Kindlegem Girdle", source="?", item_id=270230)
    row = gear_plan(_latest(), _targets(target), companion=_companion()).rows[0]
    assert (row.score_delta, row.verdict_basis) == (None, "item_level")
