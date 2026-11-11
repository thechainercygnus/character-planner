import json

from character_planner.config import Settings
from character_planner.curated import load_gear_targets
from character_planner.db import Snapshot
from character_planner.summary import build_summary, equipped_by_slot

from .conftest import FIXTURES


def snapshot(kind: str) -> Snapshot:
    payload = json.loads((FIXTURES / f"synthetic_{kind}.json").read_text(encoding="utf-8"))
    return Snapshot(source="api", kind=kind, status=200, payload=payload)


def test_equipped_by_slot_reads_retail_shape() -> None:
    equipped = equipped_by_slot(snapshot("equipment").payload)
    assert equipped["WAIST"] == "Flimsy Chain Belt (Poor)"


def test_equipped_by_slot_tolerates_unknown_shapes() -> None:
    assert equipped_by_slot({"something": "else"}) == {}
    assert equipped_by_slot("Not Found") == {}


def test_summary_compares_gear_to_level_bracket(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    latest = {"profile": snapshot("profile"), "equipment": snapshot("equipment")}

    text = build_summary("Brumboldt Doomlet", latest, targets)

    assert text.startswith("# Brumboldt Doomlet")
    assert "- Level: 15" in text
    assert "| WAIST | Flimsy Chain Belt (Poor) | Kindlegem Girdle |" in text
    assert "| BACK | done: Spiritwraith Drape (Rare) |" in text
    assert "| LEGS | empty |" in text
    assert "Next bracket at level 20" in text


def test_summary_without_snapshots_explains_next_step(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    assert "/auth/login" in build_summary("Brumboldt Doomlet", {}, targets)
