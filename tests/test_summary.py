import json

from character_planner.config import Settings
from character_planner.curated import load_gear_targets
from character_planner.db import Snapshot
from character_planner.summary import build_summary, character_level, equipped_by_slot

from .conftest import FIXTURES


def snapshot(kind: str) -> Snapshot:
    """A snapshot built from a real Forever API response (tests/fixtures/forever_*.json)."""
    payload = json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))
    return Snapshot(source="api", kind=kind, status=200, payload=payload)


def test_level_from_real_profile() -> None:
    assert character_level(snapshot("profile").payload) == 18


def test_equipped_by_slot_reads_real_equipment() -> None:
    equipped = equipped_by_slot(snapshot("equipment").payload)
    assert equipped["WAIST"] == "Belt of the People's Militia (Common)"
    assert equipped["OFF_HAND"] == "Burnished Shield (Uncommon)"
    assert equipped["HEAD"] == "Flying Tiger Goggles (Uncommon)"


def test_equipped_by_slot_tolerates_unknown_shapes() -> None:
    assert equipped_by_slot({"something": "else"}) == {}
    assert equipped_by_slot("Not Found") == {}


def test_summary_compares_real_gear_to_level_bracket(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    latest = {"profile": snapshot("profile"), "equipment": snapshot("equipment")}

    text = build_summary("Brumboldt Doomlet", latest, targets)

    assert text.startswith("# Brumboldt Doomlet")
    assert "- Level: 18" in text
    assert "| OFF_HAND | Burnished Shield (Uncommon) | Dwarven Defender |" in text
    assert "| LEGS | Stormwind Guard Leggings (Uncommon) | Direhammer Leggings |" in text
    assert "Next bracket at level 20" in text


def test_summary_marks_reached_targets_and_empty_slots(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    profile = Snapshot(source="api", kind="profile", status=200, payload={"level": 16})
    equipment = Snapshot(
        source="api",
        kind="equipment",
        status=200,
        payload={
            "equipped_items": [
                {
                    "slot": {"type": "BACK"},
                    "name": "Spiritwraith Drape",
                    "quality": {"name": "Rare"},
                }
            ]
        },
    )

    text = build_summary("Brumboldt Doomlet", {"profile": profile, "equipment": equipment}, targets)

    assert "| BACK | done: Spiritwraith Drape (Rare) |" in text
    assert "| LEGS | empty |" in text


def test_summary_without_snapshots_explains_next_step(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    assert "/auth/login" in build_summary("Brumboldt Doomlet", {}, targets)
