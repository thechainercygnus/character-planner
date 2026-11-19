"""Quest progress in planning (#186, ADR 0052): the log and completed ids from the addon's
game data, matched by quest id to reward quests, their chains, and gear targets' reward
quests."""

import json
from datetime import UTC, datetime

from character_planner.companion import parse_item
from character_planner.curated import GearTarget
from character_planner.gamedata import GameData
from character_planner.gamedata import read_export as read
from character_planner.lookahead import target_events
from character_planner.pool import PoolItem, PoolSource
from character_planner.questlog import (
    QuestState,
    mark_gear_plan,
    mark_items,
    mark_recommendations,
    quest_state,
)
from character_planner.quests import QuestStep
from character_planner.recommend import Candidate, Recommendations, SlotRecommendation
from character_planner.views import GearPlan, GearRow, QuestProgress, TargetInfo, UpcomingTarget

from .conftest import FIXTURES
from .test_gamedata import schema_example

SUMMONING = 1640  # in the schema example's log: 0 of 1 done
DONE_BEFORE = (1638, 1639)  # the schema example's completed ids
LOG_AT = datetime.fromtimestamp(1794699990, UTC)  # its quests' capturedAt


def example() -> GameData:
    return read(schema_example().encode())


def test_the_log_and_completed_ids_come_from_the_newest_import() -> None:
    state = quest_state(example())
    assert state.log[SUMMONING] == QuestProgress(
        quest_id=SUMMONING,
        title="The Summoning",
        complete=False,
        done=0,
        needed=1,
        captured_at=LOG_AT,
    )
    assert state.completed == set(DONE_BEFORE)


def test_no_quests_means_no_state() -> None:
    assert not quest_state(None)
    assert not quest_state(example().model_copy(update={"quests": None}))


def test_objectives_add_up_and_a_complete_quest_says_so() -> None:
    real = read((FIXTURES / "savedvariables" / "real_addon_0.2.0_crlf.lua").read_bytes())
    state = quest_state(real)
    gauntlet = next(q for q in state.log.values() if q.title == "The Algaz Gauntlet")
    assert (gauntlet.done, gauntlet.needed, gauntlet.complete) == (15, 15, True)


def step(quest_id: int | None, name: str) -> QuestStep:
    return QuestStep(quest_id=quest_id, name=name)


def reward(quest: QuestStep, chain: list[list[QuestStep]]) -> PoolItem:
    source = PoolSource(kind="quest", dungeon="Shadowfang Keep", quest=quest, chain=chain)
    return PoolItem(item_id=1, name="Reward", sources=[source])


def test_a_reward_quest_and_its_chain_are_marked_by_id() -> None:
    first, second = step(DONE_BEFORE[0], "Earlier"), step(DONE_BEFORE[1], "Also earlier")
    unknown = step(None, "Zone quest, no id")
    item = reward(step(SUMMONING, "The Summoning"), [[first, second], [unknown]])
    mark_items([item], quest_state(example()))
    source = item.sources[0]
    assert source.quest is not None and source.quest.progress is not None
    assert source.quest.progress.needed == 1 and not source.quest.completed
    assert first.completed and second.completed and first.progress is None
    assert unknown.progress is None and not unknown.completed


def test_upgrades_are_marked_and_nothing_without_quests_changes() -> None:
    item = reward(step(SUMMONING, "The Summoning"), [])
    rec = Recommendations(
        level=24,
        window=(21, 34),
        rows=[
            SlotRecommendation(
                slot="BACK",
                equipped=None,
                candidates=[Candidate(item=item, score_gain=2, usable_now=True)],
            )
        ],
        dungeons=[],
        considered=1,
        unscored=0,
    )
    assert mark_recommendations(rec, QuestState()) is rec
    assert item.sources[0].quest is not None and item.sources[0].quest.progress is None
    mark_recommendations(rec, quest_state(example()))
    assert item.sources[0].quest.progress is not None


def test_forever_companion_names_the_rewarding_quests_by_id() -> None:
    # Catacomb Cloak, from GET /items/279899 (2026-11-18): "An Ancient Grudge" gives it.
    payload = json.loads((FIXTURES / "companion_item_279899.json").read_text(encoding="utf-8"))
    info = parse_item(payload)
    assert info is not None
    assert info.reward_quest_ids == [96395]
    assert info.rewards == ["Quest: An Ancient Grudge"]


def target(slot: str, item: str) -> GearTarget:
    return GearTarget(slot=slot, item=item, source="quest")


def test_a_targets_reward_quest_in_the_log_shows_on_the_plan_and_in_look_ahead() -> None:
    info = TargetInfo(sources=["companion"], item_id=279899, reward_quest_ids=[SUMMONING])
    upcoming = UpcomingTarget(target=target("BACK", "Catacomb Cloak"), target_info=info, level=26)
    row = GearRow(
        slot="BACK",
        equipped=None,
        target=target("BACK", "Catacomb Cloak"),
        target_info=info,
        reached=False,
        verdict="upgrade",
        item_level_delta=None,
        warning=None,
        upcoming=[upcoming],
    )
    worn = row.model_copy(update={"slot": "CHEST", "reached": True, "upcoming": []})
    plan = mark_gear_plan(GearPlan(level=24, rows=[row, worn]), quest_state(example()))
    assert plan.rows[0].quest is not None and plan.rows[0].quest.title == "The Summoning"
    assert plan.rows[1].quest is None  # reached: it's worn
    (event,) = [e for _, e in target_events(plan, 24, 27)]
    assert event.quest is not None and event.quest.quest_id == SUMMONING
