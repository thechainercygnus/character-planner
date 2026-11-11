import json
from typing import Any

from character_planner.curated import Bracket, GearTarget, GearTargets
from character_planner.db import CatalogItem, Snapshot
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

    assert row.target_info is not None and row.target_info.source == "api"
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

    assert row.target_info is not None and row.target_info.source == "manual"
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
