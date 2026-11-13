from character_planner.config import Settings
from character_planner.curated import load_gear_targets


def test_real_gear_targets_file_loads(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    assert len(targets.targets) == 25
    assert {t.level for t in targets.targets} == {15, 20}
    back = targets.for_slot("BACK")
    assert [(t.item, t.level, t.priority) for t in back] == [
        ("Spiritwraith Drape", 15, 1),
        ("Cape of the Brotherhood", 20, 2),
    ]
    assert targets.slots()[0] == "HEAD"
