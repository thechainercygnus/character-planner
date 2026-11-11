from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.config import Settings
from character_planner.scoring import (
    Weights,
    current_weights,
    load_default_weights,
    reset_weights,
    save_weights,
    score,
)

WEIGHTS = Weights(
    weights={"Stamina": 1.0, "Armor": 0.1, "Strength": 0.5, "Weapon DPS": 1.5, "Ranged DPS": 0.2}
)


def test_score_sums_weighted_stats_armor_and_dps() -> None:
    assert score(WEIGHTS, slot="WAIST", armor=100, stats={"Stamina": 7}, dps=None) == 17.0
    assert score(WEIGHTS, slot="MAIN_HAND", armor=None, stats={"Strength": 4}, dps=12.3) == 20.45


def test_ranged_dps_uses_its_own_weight() -> None:
    assert score(WEIGHTS, slot="RANGED", armor=None, stats={}, dps=10.0) == 2.0


def test_unweighted_stats_count_zero() -> None:
    assert score(WEIGHTS, slot="NECK", armor=None, stats={"Spirit": 5}, dps=None) == 0.0


def test_default_weights_file_loads(settings: Settings) -> None:
    defaults = load_default_weights(settings.curated_dir / "stat_weights.yaml")
    assert defaults.of("Stamina") == 1.0
    assert defaults.of("Armor") > 0


def test_saved_weights_override_defaults_until_reset(engine: Engine) -> None:
    with Session(engine) as session:
        assert current_weights(session, WEIGHTS) == WEIGHTS
        save_weights(session, {"Stamina": 3.0})
        merged = current_weights(session, WEIGHTS)
        assert merged.of("Stamina") == 3.0
        assert merged.of("Armor") == 0.1  # not saved: default
        reset_weights(session)
        assert current_weights(session, WEIGHTS) == WEIGHTS
