"""Shipped defaults per class (#80, ADR 0023)."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.app import create_app
from character_planner.classes import (
    character_class_key,
    class_key,
    current_defaults,
    load_class_defaults,
    supported_classes,
)
from character_planner.config import Settings
from character_planner.db import ActiveWeightPreset, Snapshot
from character_planner.rules import ARMOR_TYPES, OFF_HAND_TYPES, TWO_HAND_TYPES, WEAPON_TYPES

from .conftest import FIXTURES, REPO_ROOT, api_client, tracked

CURATED = REPO_ROOT / "data" / "curated"


def profile(session: Session, class_name: str, level: int = 20) -> None:
    session.add(
        Snapshot(
            character_id=tracked(session),
            source="api",
            kind="profile",
            status=200,
            payload={"level": level, "character_class": {"name": class_name}},
        )
    )
    session.commit()


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with api_client(create_app(settings, engine)) as test_client:
        yield test_client


def test_class_keys() -> None:
    assert class_key("Warlock") == "warlock"
    assert class_key("Death Knight") == "death-knight"


def test_supported_classes_start_with_the_warrior() -> None:
    assert [c.name for c in supported_classes(CURATED)] == [
        "Warrior",
        "Druid",
        "Hunter",
        "Mage",
        "Paladin",
        "Priest",
        "Rogue",
        "Shaman",
        "Warlock",
    ]


def test_every_class_in_forever_has_defaults() -> None:
    """Forever's classes, as its talent tree index names them (a real response)."""
    index = json.loads((FIXTURES / "talent_tree_index.json").read_text(encoding="utf-8"))
    forever = {tree["name"] for tree in index["class_talent_trees"]}
    assert {c.name for c in supported_classes(CURATED)} == forever


@pytest.mark.parametrize("key", [c.key for c in supported_classes(CURATED)])
def test_each_classs_defaults_use_values_the_editor_offers(key: str) -> None:
    defaults = load_class_defaults(CURATED, key)
    rules = defaults.rules
    assert defaults.playable.key == key
    assert set(rules.weapon_types) <= set(WEAPON_TYPES)
    assert set(rules.armor_types) <= set(ARMOR_TYPES)
    assert set(rules.off_hand_types) <= set(OFF_HAND_TYPES)
    if rules.two_hand_types is not None:
        assert rules.two_handers and set(rules.two_hand_types) <= set(TWO_HAND_TYPES)
        # A two-hander type the class can't otherwise wield would never be suggested.
        assert set(rules.two_hand_types) <= set(rules.weapon_types)
    presets = defaults.presets.presets
    assert presets and all(p.key.startswith(f"{key}-") or key == "warrior" for p in presets)
    assert all(weight >= 0 for p in presets for weight in p.weights.values())


def test_mail_and_plate_come_at_40_for_the_classes_that_wear_them() -> None:
    levels = {}
    for playable in supported_classes(CURATED):
        rules = load_class_defaults(CURATED, playable.key).rules
        if (rules.mail_from_level, rules.plate_from_level) != (None, None):
            levels[playable.key] = (rules.mail_from_level, rules.plate_from_level)
    assert levels == {
        "hunter": (40, None),
        "shaman": (40, None),
        "paladin": (None, 40),
        "warrior": (None, 40),
    }


def test_preset_keys_are_unique_across_classes() -> None:
    keys = [
        p.key
        for c in supported_classes(CURATED)
        for p in load_class_defaults(CURATED, c.key).presets.presets
    ]
    assert len(keys) == len(set(keys))


def test_the_warlock_defaults() -> None:
    warlock = load_class_defaults(CURATED, "warlock")
    rules = warlock.rules
    assert (rules.armor_types, rules.plate_from_level, rules.mail_from_level) == (
        ["cloth"],
        None,
        None,
    )
    assert rules.weapon_types == ["Dagger", "Sword", "Staff", "Wand"]
    assert (rules.two_handers, rules.two_hand_types) == (True, ["Staff"])
    assert rules.off_hand_types == ["Miscellaneous"]
    # The Upgrades tuning is shared with the Warrior's recommend.yaml.
    warrior = load_class_defaults(CURATED, "warrior")
    assert (rules.levels_ahead, rules.per_slot, rules.min_gain) == (
        warrior.rules.levels_ahead,
        warrior.rules.per_slot,
        warrior.rules.min_gain,
    )
    leveling, dungeon = warlock.presets.presets
    assert (leveling.key, dungeon.key) == ("warlock-leveling", "warlock-dungeon")
    assert leveling.weights["Spell Damage"] == 1.0 and leveling.weights["Strength"] == 0.0
    # A later preset only lists its changes; the rest comes from the first.
    assert dungeon.weights["Spell Damage"] == 1.0 and dungeon.weights["Ranged DPS"] == 0.3
    assert warlock.targets.targets == []
    assert warlock.talent_plan.steps == []


def test_a_class_without_defaults_gets_the_warriors() -> None:
    assert load_class_defaults(CURATED, "death-knight").playable.key == "warrior"


def test_the_class_comes_from_the_synced_profile(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        assert character_class_key(session, tracked(session)) is None
        assert (
            current_defaults(session, CURATED, tracked(session)).playable.key == "warrior"
        )  # before a sync
        profile(session, "Warlock")
        assert character_class_key(session, tracked(session)) == "warlock"
        assert current_defaults(session, CURATED, tracked(session)).playable.key == "warlock"


def test_a_warlock_gets_warlock_defaults_everywhere(client: TestClient, engine: Engine) -> None:
    warrior_rules = client.get("/api/rules").json()["defaults"]
    assert "plate" not in warrior_rules["armor_types"] and warrior_rules["plate_from_level"] == 40

    with Session(engine) as session:
        profile(session, "Warlock")

    rules = client.get("/api/rules").json()
    assert rules["defaults"]["armor_types"] == ["cloth"]
    assert rules["rules"] == rules["defaults"]
    weights = client.get("/api/weights").json()
    assert weights["preset"] == "warlock-leveling"
    assert [p["key"] for p in weights["presets"]] == ["warlock-leveling", "warlock-dungeon"]
    assert client.get("/api/targets").json()["targets"] == []
    gear = client.get("/api/gear").json()
    assert (gear["rows"], gear["later"]) == ([], [])
    talents = client.get("/api/talents")
    assert talents.status_code == 200
    assert talents.json()["customised"] is False


def test_a_warrior_preset_left_active_falls_back_to_the_class_default(
    client: TestClient, engine: Engine
) -> None:
    with Session(engine) as session:
        session.add(ActiveWeightPreset(id=1, key="dungeon-tank"))
        session.commit()
    assert client.get("/api/weights").json()["preset"] == "dungeon-tank"
    with Session(engine) as session:
        profile(session, "Warlock")
    assert client.get("/api/weights").json()["preset"] == "warlock-leveling"


def test_guest_mode_offers_each_class_with_its_presets(client: TestClient) -> None:
    classes = {c["key"]: c for c in client.get("/api/guest").json()["classes"]}
    assert [p["name"] for p in classes["warlock"]["presets"]] == [
        "Leveling caster",
        "Dungeon caster",
    ]
    ok = client.get("/api/guest/recommendations", params={"level": 20, "class": "warlock"})
    assert ok.status_code == 200
    warrior_preset = client.get(
        "/api/guest/recommendations",
        params={"level": 20, "class": "warlock", "preset": "leveling-tank"},
    )
    assert warrior_preset.status_code == 422  # presets belong to their class
    unknown = client.get(
        "/api/guest/recommendations", params={"level": 20, "class": "death-knight"}
    )
    assert unknown.status_code == 422


@pytest.mark.parametrize(
    "key", ["../recommend", "..\recommend", "../../pyproject", "/etc/passwd", "warlock/../x", ""]
)
def test_a_key_can_only_name_a_shipped_class_file(key: str) -> None:
    """Keys come from outside (guest mode, a Blizzard profile): one that isn't a shipped
    class gets the Warrior's defaults, never a file elsewhere."""
    assert load_class_defaults(CURATED, key).playable.key == "warrior"


def test_an_odd_class_name_in_a_profile_is_harmless(engine: Engine) -> None:
    with Session(engine) as session:
        profile(session, "../../Recommend")
        assert current_defaults(session, CURATED, tracked(session)).playable.key == "warrior"


def test_guest_mode_refuses_a_path_as_a_class(client: TestClient) -> None:
    response = client.get(
        "/api/guest/recommendations", params={"level": 20, "class": "../recommend"}
    )
    assert response.status_code == 422


def test_dual_wield_levels() -> None:
    """Rogues learn Dual Wield at 10, Warriors and Hunters at 20 (Forever, per Bryce)."""
    levels = {
        c.key: load_class_defaults(CURATED, c.key).rules.dual_wield_from_level
        for c in supported_classes(CURATED)
    }
    assert {key: level for key, level in levels.items() if level is not None} == {
        "rogue": 10,
        "hunter": 20,
        "warrior": 20,
    }
    # Classes without it put no weapons in the off hand.
    for key, level in levels.items():
        if level is None:
            off_hand = load_class_defaults(CURATED, key).rules.off_hand_types
            assert set(off_hand) <= {"Shield", "Miscellaneous"}, key
