"""Quest progress in planning (#186, ADR 0052).

The addon's game data has the quest log, with each objective's count, and the ids of the
quests the game reports completed. They're matched by quest id to the quests the planner
already describes:
- a quest-reward source, and each step of its chain, on the Upgrades and Dungeons views;
- a gear target's reward quests (Forever Companion's `rewardFrom[].questId`), on the Plan
  tab and in Look ahead.

Nothing is re-ranked or hidden: the progress rides on the views.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlmodel import Session

from character_planner.gamedata import GameData, moment, stored
from character_planner.pool import PoolItem
from character_planner.quests import QuestStep
from character_planner.recommend import Recommendations
from character_planner.views import GearPlan, QuestProgress, TargetInfo


@dataclass
class QuestState:
    log: dict[int, QuestProgress] = field(default_factory=dict[int, QuestProgress])
    completed: set[int] = field(default_factory=set[int])

    def __bool__(self) -> bool:
        return bool(self.log or self.completed)


def quest_state(data: GameData | None) -> QuestState:
    """The log by quest id, and the completed ids, from the newest import."""
    state = QuestState()
    if data is None or data.quests is None:
        return state
    at = moment(data.quests.captured_at)
    for quest in data.quests.log:
        state.log[quest.quest_id] = QuestProgress(
            quest_id=quest.quest_id,
            title=quest.title,
            complete=quest.complete,
            done=sum(o.done for o in quest.objectives),
            needed=sum(o.needed for o in quest.objectives),
            captured_at=at,
        )
    state.completed = set(data.quests.completed)
    return state


def quest_state_for(session: Session, character_id: int | None) -> QuestState:
    if character_id is None:
        return QuestState()
    row = stored(session, character_id)
    return quest_state(GameData.model_validate(row.data) if row is not None else None)


def _mark(step: QuestStep | None, state: QuestState) -> None:
    if step is None or step.quest_id is None:
        return
    step.progress = state.log.get(step.quest_id)
    step.completed = step.quest_id in state.completed


def mark_items(items: Iterable[PoolItem], state: QuestState) -> None:
    """Every quest a pool item's sources name: the reward's quest and its chain."""
    for item in items:
        for source in item.sources:
            _mark(source.quest, state)
            for quests in source.chain:
                for step in quests:
                    _mark(step, state)


def mark_recommendations(rec: Recommendations, state: QuestState) -> Recommendations:
    if not state:
        return rec
    mark_items((c.item for row in rec.rows for c in row.candidates), state)
    for dungeon in rec.dungeons:
        mark_items((u.item for u in dungeon.upgrades), state)
        for upgrade in dungeon.upgrades:
            _mark(upgrade.source.quest, state)
    return rec


def _in_log(info: TargetInfo | None, state: QuestState) -> QuestProgress | None:
    """The first of a target's reward quests that's in the log."""
    if info is None:
        return None
    return next((state.log[q] for q in info.reward_quest_ids if q in state.log), None)


def mark_gear_plan(plan: GearPlan, state: QuestState) -> GearPlan:
    """Targets whose reward quest is in the log; a reached target is worn already."""
    if not state.log:
        return plan
    for row in plan.rows:
        row.quest = None if row.reached else _in_log(row.target_info, state)
        for upcoming in row.upcoming:
            upcoming.quest = _in_log(upcoming.target_info, state)
    for slot in plan.later:
        for upcoming in slot.upcoming:
            upcoming.quest = _in_log(upcoming.target_info, state)
    return plan
