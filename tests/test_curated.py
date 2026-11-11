from character_planner.config import Settings
from character_planner.curated import load_gear_targets


def test_real_gear_targets_file_loads(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    assert [b.min_level for b in targets.brackets] == [15, 20]


def test_bracket_selection(settings: Settings) -> None:
    targets = load_gear_targets(settings.curated_dir / "gear_targets.yaml")
    assert targets.for_level(10) is None
    bracket_17 = targets.for_level(17)
    assert bracket_17 is not None and bracket_17.min_level == 15
    bracket_22 = targets.for_level(22)
    assert bracket_22 is not None and bracket_22.min_level == 20
    upcoming = targets.next_after(17)
    assert upcoming is not None and upcoming.min_level == 20
    assert targets.next_after(25) is None
