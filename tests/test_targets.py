from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.choices import set_choice, take_target_choices
from character_planner.curated import Bracket, GearTarget, GearTargets
from character_planner.db import ItemChoice
from character_planner.pool import PoolItem, PoolSource
from character_planner.targets import (
    current_targets,
    is_customised,
    pin_target,
    pinned_ids,
    reset_targets,
    save_targets,
    source_text,
    unpin_target,
)

DEFAULT = GearTargets(
    brackets=[
        Bracket(
            min_level=15, targets=[GearTarget(slot="WAIST", item="Belt", source="x", item_id=1)]
        ),
        Bracket(
            min_level=20, targets=[GearTarget(slot="BACK", item="Cape", source="y", item_id=2)]
        ),
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
        assert current_targets(session, DEFAULT) == DEFAULT
        assert not is_customised(session)
        edited = GearTargets(brackets=DEFAULT.brackets[:1])
        save_targets(session, edited)
        assert current_targets(session, DEFAULT) == edited
        assert is_customised(session)
        reset_targets(session)
        assert current_targets(session, DEFAULT) == DEFAULT


def test_source_text_matches_the_yaml_style() -> None:
    assert source_text(DROP) == "The Deadmines - Edwin VanCleef"
    assert source_text(QUEST) == "Quest: The Defias Brotherhood (The Deadmines)"


def test_pins_go_into_the_bracket_for_the_level() -> None:
    pinned = pin_target(DEFAULT, pool_item(5, DROP, QUEST), "FINGER_2", level=18)
    added = pinned.brackets[0].targets[-1]
    assert (added.slot, added.item, added.item_id, added.priority) == ("FINGER_2", "Item 5", 5, 2)
    assert (
        added.source
        == "The Deadmines - Edwin VanCleef; Quest: The Defias Brotherhood (The Deadmines)"
    )
    assert DEFAULT.brackets[0].targets[-1].item_id == 1  # the input isn't changed
    assert pin_target(pinned, pool_item(5), "FINGER_2", level=18) == pinned  # once
    assert pinned_ids(pinned, 18) == {1, 5}
    assert pinned_ids(pinned, 22) == {2}


def test_a_pin_below_every_bracket_starts_one_at_the_level() -> None:
    pinned = pin_target(DEFAULT, pool_item(5), "BACK", level=12)
    assert [b.min_level for b in pinned.brackets] == [12, 15, 20]
    assert [t.item_id for t in pinned.brackets[0].targets] == [5]


def test_unpin_removes_from_the_current_bracket_only() -> None:
    assert unpin_target(DEFAULT, 2, level=18) is None  # a level-20 target
    unpinned = unpin_target(DEFAULT, 1, level=18)
    assert unpinned is not None
    assert unpinned.brackets[0].targets == []
    assert unpinned.brackets[1] == DEFAULT.brackets[1]


def test_old_target_choices_are_taken_once(engine: Engine) -> None:
    with Session(engine) as session:
        set_choice(session, 9, "Dismissed", "dismissed")
        session.add(ItemChoice(item_id=7, choice="target", name="Pinned"))
        session.commit()
        assert take_target_choices(session) == [7]
        assert take_target_choices(session) == []
        assert session.get(ItemChoice, 9) is not None  # dismissals stay
