import json

from character_planner.db import Snapshot
from character_planner.views import (
    character_view,
    parse_equipment,
    parse_professions,
    parse_specialization,
    parse_stats,
)

from .conftest import FIXTURES


def payload(kind: str) -> object:
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
