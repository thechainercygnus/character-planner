import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.recommend import load_rules
from character_planner.rules import (
    ARMOR_TYPES,
    OFF_HAND_TYPES,
    WEAPON_TYPES,
    EditedRules,
    RulesError,
    current_rules,
    reset_rules,
    rules_view,
    save_rules,
)

from .conftest import REPO_ROOT, tracked

DEFAULT = load_rules(REPO_ROOT / "data" / "curated" / "recommend.yaml")


def edited(**changes: object) -> EditedRules:
    return EditedRules.model_validate(DEFAULT.model_dump() | changes)


def test_the_shipped_rules_are_all_offered_by_the_editor() -> None:
    assert set(DEFAULT.weapon_types) <= set(WEAPON_TYPES)
    assert set(DEFAULT.armor_types) <= set(ARMOR_TYPES)
    assert set(DEFAULT.off_hand_types) <= set(OFF_HAND_TYPES)
    assert edited().to_rules() == DEFAULT


def test_stored_rules_win_until_reset(engine: Engine) -> None:
    with Session(engine) as session:
        assert current_rules(session, DEFAULT, tracked(session)) == DEFAULT
        assert rules_view(session, DEFAULT, tracked(session)).customised is False
        dagger_only = edited(weapon_types=["Dagger"], per_slot=5).to_rules()
        save_rules(session, dagger_only, tracked(session))
        view = rules_view(session, DEFAULT, tracked(session))
        assert (view.rules, view.defaults, view.customised) == (dagger_only, DEFAULT, True)
        reset_rules(session, tracked(session))
        assert current_rules(session, DEFAULT, tracked(session)) == DEFAULT
        reset_rules(session, tracked(session))  # nothing to reset is fine


def test_lists_follow_the_editors_order_without_repeats() -> None:
    rules = edited(weapon_types=["Gun", "Axe", "Gun"], armor_types=["mail", "cloth"]).to_rules()
    assert rules.weapon_types == ["Axe", "Gun"]
    assert rules.armor_types == ["cloth", "mail"]


@pytest.mark.parametrize(
    "changes",
    [
        {"weapon_types": ["Lightsaber"]},
        {"armor_types": ["plate"]},  # plate comes from plate_from_level
        {"off_hand_types": ["Wand"]},
    ],
)
def test_unknown_types_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(RulesError):
        edited(**changes).to_rules()


@pytest.mark.parametrize(
    "changes",
    [
        {"plate_from_level": 0},
        {"plate_from_level": 81},
        {"levels_ahead": -1},
        {"levels_ahead": 21},
        {"per_slot": 0},
        {"per_slot": 11},
        {"min_gain": -1},
        {"min_gain": float("inf")},
    ],
)
def test_numbers_are_bounded(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        edited(**changes)


def test_plate_can_be_turned_off() -> None:
    assert edited(plate_from_level=None).to_rules().plate_from_level is None


def test_two_hand_types_are_validated_and_none_means_any() -> None:
    rules = edited(two_handers=True, two_hand_types=["Staff", "Axe", "Staff"]).to_rules()
    assert rules.two_hand_types == ["Axe", "Staff"]
    assert edited(two_hand_types=None).to_rules().two_hand_types is None
    with pytest.raises(RulesError):
        edited(two_hand_types=["Wand"]).to_rules()


def test_mail_level_is_bounded() -> None:
    assert edited(mail_from_level=40).to_rules().mail_from_level == 40
    with pytest.raises(ValueError):
        edited(mail_from_level=0)


def test_dual_wield_level_is_bounded_and_optional() -> None:
    assert edited(dual_wield_from_level=20).to_rules().dual_wield_from_level == 20
    assert edited(dual_wield_from_level=None).to_rules().dual_wield_from_level is None
    with pytest.raises(ValueError):
        edited(dual_wield_from_level=81)
