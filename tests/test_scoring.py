from collections.abc import Callable

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.config import Settings
from character_planner.db import ActiveWeightPreset, StoredWeights
from character_planner.scoring import (
    LEVELING,
    Preset,
    PresetError,
    ShippedPresets,
    UnknownPreset,
    Weights,
    activate,
    active_key,
    create_preset,
    current_weights,
    delete_preset,
    load_default_weights,
    load_shipped_presets,
    migrate_stored_weights,
    rename_preset,
    reset_weights,
    save_weights,
    score,
    weights_view,
)

from .conftest import tracked

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


SHIPPED = ShippedPresets(
    presets=[
        Preset(key=LEVELING, name="Leveling tank", weights={"Stamina": 1.0, "Armor": 0.1}),
        Preset(key="solo-dps", name="Solo DPS", weights={"Stamina": 0.5, "Armor": 0.03}),
    ]
)


def test_shipped_presets_load_with_leveling_tank_first(settings: Settings) -> None:
    shipped = load_shipped_presets(settings.curated_dir)
    assert [p.key for p in shipped.presets] == [LEVELING, "dungeon-tank", "solo-dps"]
    base = load_default_weights(settings.curated_dir / "stat_weights.yaml")
    assert shipped.base == base
    solo = shipped.get("solo-dps")
    assert solo is not None and solo.weights["Strength"] == 1.0
    # Stats a preset leaves out take the Leveling tank weight.
    assert solo.weights["Fire Resistance"] == base.of("Fire Resistance")


def test_leveling_tank_is_active_by_default_and_edits_win_until_reset(engine: Engine) -> None:
    with Session(engine) as session:
        assert current_weights(session, SHIPPED, tracked(session)) == SHIPPED.base
        save_weights(session, SHIPPED, {"Stamina": 3.0}, tracked(session))
        merged = current_weights(session, SHIPPED, tracked(session))
        assert (merged.of("Stamina"), merged.of("Armor")) == (3.0, 0.1)  # Armor: default
        view = weights_view(session, SHIPPED, tracked(session))
        assert view.customised and view.defaults == {"Stamina": 1.0, "Armor": 0.1}
        assert [(p.key, p.customised) for p in view.presets] == [
            (LEVELING, True),
            ("solo-dps", False),
        ]
        reset_weights(session, SHIPPED, tracked(session))
        assert current_weights(session, SHIPPED, tracked(session)) == SHIPPED.base


def test_switching_presets_keeps_each_ones_edits(engine: Engine) -> None:
    with Session(engine) as session:
        save_weights(session, SHIPPED, {"Stamina": 3.0}, tracked(session))
        activate(session, SHIPPED, "solo-dps", tracked(session))
        assert current_weights(session, SHIPPED, tracked(session)).of("Stamina") == 0.5
        activate(session, SHIPPED, LEVELING, tracked(session))
        assert current_weights(session, SHIPPED, tracked(session)).of("Stamina") == 3.0
        with pytest.raises(UnknownPreset):
            activate(session, SHIPPED, "nope", tracked(session))


def test_own_presets_can_be_saved_renamed_and_deleted(engine: Engine) -> None:
    with Session(engine) as session:
        key = create_preset(session, SHIPPED, "  Raid   tank ", {"Stamina": 2.0}, tracked(session))
        assert key == "raid-tank"
        view = weights_view(session, SHIPPED, tracked(session))
        assert view.preset == "raid-tank"
        assert view.weights == {"Stamina": 2.0, "Armor": 0.1}  # missing stats: Leveling tank
        assert not view.customised
        assert view.presets[-1].model_dump() == {
            "key": "raid-tank",
            "name": "Raid tank",
            "shipped": False,
            "customised": False,
        }
        # Edits replace its weights; there's nothing to reset to.
        save_weights(session, SHIPPED, {"Stamina": 2.5}, tracked(session))
        assert current_weights(session, SHIPPED, tracked(session)).of("Stamina") == 2.5
        with pytest.raises(PresetError):
            reset_weights(session, SHIPPED, tracked(session))

        assert create_preset(session, SHIPPED, "Raid tank!", {}, tracked(session)) == "raid-tank-2"
        rename_preset(session, SHIPPED, "raid-tank-2", "Off tank", tracked(session))
        names = [p.name for p in weights_view(session, SHIPPED, tracked(session)).presets]
        assert names == ["Leveling tank", "Solo DPS", "Off tank", "Raid tank"]  # yours: by name

        delete_preset(session, SHIPPED, "raid-tank-2", tracked(session))  # the active one
        assert weights_view(session, SHIPPED, tracked(session)).preset == LEVELING
        assert [p.key for p in weights_view(session, SHIPPED, tracked(session)).presets] == [
            LEVELING,
            "solo-dps",
            "raid-tank",
        ]


@pytest.mark.parametrize(
    ("action", "error"),
    [
        (
            lambda s: create_preset(s, SHIPPED, "solo dps", {}, tracked(s)),
            PresetError,
        ),  # name taken
        (lambda s: create_preset(s, SHIPPED, " ", {}, tracked(s)), PresetError),
        (lambda s: create_preset(s, SHIPPED, "x" * 41, {}, tracked(s)), PresetError),
        (lambda s: rename_preset(s, SHIPPED, "solo-dps", "Mine", tracked(s)), PresetError),
        (lambda s: delete_preset(s, SHIPPED, LEVELING, tracked(s)), PresetError),
        (lambda s: rename_preset(s, SHIPPED, "nope", "Mine", tracked(s)), UnknownPreset),
        (lambda s: delete_preset(s, SHIPPED, "nope", tracked(s)), UnknownPreset),
    ],
)
def test_preset_requests_that_cannot_be_done(
    engine: Engine, action: Callable[[Session], object], error: type[Exception]
) -> None:
    with Session(engine) as session, pytest.raises(error):
        action(session)


def test_a_deleted_active_preset_falls_back_to_leveling_tank(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(ActiveWeightPreset(character_id=tracked(session), key="gone"))
        session.commit()
        assert active_key(session, SHIPPED, tracked(session)) == LEVELING


def test_weights_saved_before_presets_move_into_leveling_tank(engine: Engine) -> None:
    with Session(engine) as session:
        assert not migrate_stored_weights(session, tracked(session))
        session.add(StoredWeights(id=1, weights={"Stamina": 4.0}))
        session.commit()
        assert migrate_stored_weights(session, tracked(session))
        assert session.get(StoredWeights, 1) is None
        assert current_weights(session, SHIPPED, tracked(session)).of("Stamina") == 4.0
        assert not migrate_stored_weights(session, tracked(session))  # once
