from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.choices import set_choice, take_target_choices
from character_planner.curated import GearTarget, GearTargets
from character_planner.db import ItemChoice, owned
from character_planner.pool import PoolItem, PoolSource
from character_planner.targets import (
    EditedTargets,
    TargetsError,
    current_targets,
    is_customised,
    pin_target,
    reset_targets,
    save_targets,
    source_text,
    unpin_target,
)

from .conftest import tracked

DEFAULT = GearTargets(
    targets=[
        GearTarget(slot="WAIST", item="Belt", source="x", item_id=1, level=15),
        GearTarget(slot="BACK", item="Cape", source="y", item_id=2, level=20),
    ]
)
DROP = PoolSource(
    kind="drop", dungeon_id="the-deadmines", dungeon="The Deadmines", detail="Edwin VanCleef"
)
QUEST = PoolSource(
    kind="quest",
    dungeon_id="the-deadmines",
    dungeon="The Deadmines",
    detail="The Defias Brotherhood",
)


def pool_item(item_id: int, *sources: PoolSource) -> PoolItem:
    return PoolItem(item_id=item_id, name=f"Item {item_id}", sources=list(sources or [DROP]))


def test_stored_targets_win_until_reset(engine: Engine) -> None:
    with Session(engine) as session:
        assert current_targets(session, DEFAULT, tracked(session)) == DEFAULT
        assert not is_customised(session, tracked(session))
        edited = GearTargets(targets=DEFAULT.targets[:1])
        save_targets(session, edited, tracked(session))
        assert current_targets(session, DEFAULT, tracked(session)) == edited
        assert is_customised(session, tracked(session))
        reset_targets(session, tracked(session))
        assert current_targets(session, DEFAULT, tracked(session)) == DEFAULT


def test_source_text_matches_the_yaml_style() -> None:
    assert source_text(DROP) == "The Deadmines - Edwin VanCleef"
    assert source_text(QUEST) == "Quest: The Defias Brotherhood (The Deadmines)"


def test_pins_join_their_slot_at_the_items_own_level() -> None:
    pinned = pin_target(DEFAULT, pool_item(5, DROP, QUEST), "BACK")
    added = pinned.targets[-1]
    assert (added.slot, added.item, added.item_id, added.level) == ("BACK", "Item 5", 5, None)
    assert added.priority == 2  # after the Cape, the slot's first target
    assert added.pinned
    assert (
        added.source
        == "The Deadmines - Edwin VanCleef; Quest: The Defias Brotherhood (The Deadmines)"
    )
    assert len(DEFAULT.targets) == 2  # the input isn't changed
    assert pin_target(pinned, pool_item(5), "BACK") == pinned  # once
    assert pinned.pinned_ids() == {5}  # YAML targets aren't pinned


def test_pinning_an_existing_target_marks_it() -> None:
    pinned = pin_target(DEFAULT, pool_item(1), "WAIST")
    assert [(t.item_id, t.pinned) for t in pinned.targets] == [(1, True), (2, False)]


def test_unpin_takes_the_pin_off_and_keeps_the_target() -> None:
    assert unpin_target(DEFAULT, 1) is None  # not pinned
    pinned = pin_target(DEFAULT, pool_item(1), "WAIST")  # a YAML target
    assert unpin_target(pinned, 1) == DEFAULT
    unpinned = unpin_target(pin_target(DEFAULT, pool_item(5), "BACK"), 5)
    assert unpinned is not None
    assert [(t.item_id, t.pinned) for t in unpinned.targets] == [(1, False), (2, False), (5, False)]


def test_priority_is_the_position_within_each_slot() -> None:
    targets = GearTargets(
        targets=[
            GearTarget(slot="BACK", item="A", source="", priority=9),
            GearTarget(slot="WAIST", item="B", source=""),
            GearTarget(slot="BACK", item="C", source=""),
        ]
    )
    assert [(t.item, t.priority) for t in targets.targets] == [("A", 1), ("B", 1), ("C", 2)]


def test_bracketed_targets_become_levels() -> None:
    """Targets saved in brackets (ADR 0014) read as a flat list (ADR 0015)."""
    old = {
        "brackets": [
            {"min_level": 20, "targets": [{"slot": "BACK", "item": "Late", "source": ""}]},
            {
                "min_level": 15,
                "targets": [
                    {"slot": "BACK", "item": "Second", "source": "", "priority": 2},
                    {"slot": "BACK", "item": "First", "source": "", "priority": 1},
                    {"slot": "BACK", "item": "Planned", "source": "", "level": 17},
                ],
            },
        ]
    }
    targets = GearTargets.model_validate(old)
    assert [(t.item, t.level, t.priority) for t in targets.targets] == [
        ("First", 15, 1),
        ("Second", 15, 2),
        ("Planned", 17, 3),
        ("Late", 20, 4),
    ]


def test_edits_are_validated() -> None:
    edited = EditedTargets.model_validate(
        {"targets": [{"slot": "BACK", "item": "  Cape ", "level": 20}]}
    )
    assert edited.to_targets().targets[0].item == "Cape"
    bad = EditedTargets.model_validate({"targets": [{"slot": "TABARD", "item": "Cape"}]})
    try:
        bad.to_targets()
    except TargetsError:
        pass
    else:
        raise AssertionError("an unknown slot should be refused")


def test_old_target_choices_are_taken_once(engine: Engine) -> None:
    with Session(engine) as session:
        set_choice(session, 9, "Dismissed", "dismissed", tracked(session))
        session.add(
            ItemChoice(character_id=tracked(session), item_id=7, choice="target", name="Pinned")
        )
        session.commit()
        assert take_target_choices(session, tracked(session)) == [7]
        assert take_target_choices(session, tracked(session)) == []
        assert owned(session, ItemChoice, tracked(session), item_id=9) is not None  # stays
