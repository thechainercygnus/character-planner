"""Look ahead to the next levels (#4, ADR 0032): what each coming level brings.

Built from views the app already makes, so each fact keeps one source:

- dungeons whose minimum level falls in the range (ADR 0006), for the character's
  faction;
- gear targets coming up in the gear plan (ADR 0014, 0015);
- the talent plan's points, one per level (ADR 0009, #88);
- class quests becoming available (#8);
- profession ranks whose level requirement is met (#10).
"""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from character_planner.class_quests import ClassQuestChecklist
from character_planner.crafting import ProfessionsView
from character_planner.dungeons import Dungeon
from character_planner.talents import TalentPlanView, level_for_point, points_at
from character_planner.views import GearPlan

DEFAULT_LEVELS = 5
MAX_LEVELS = 10
MAX_LEVEL = 60  # nothing to look ahead to past the level cap

EventKind = Literal["dungeon", "target", "talent", "class_quest", "profession"]


class LookAheadEvent(BaseModel):
    kind: EventKind
    title: str
    detail: str | None = None
    essential: bool = False  # an essential class quest
    pinned: bool = False  # a pinned gear target
    locked: bool = False  # a dungeon not open yet in Forever
    link: str | None = None


class LevelGroup(BaseModel):
    level: int
    events: list[LookAheadEvent]


class LookAhead(BaseModel):
    level: int | None
    levels: int  # how far ahead, as asked
    groups: list[LevelGroup]  # each coming level with something on it, in order


def slot_label(slot: str) -> str:
    """ "MAIN_HAND" -> "Main Hand", as the frontend's slotLabel."""
    return " ".join(word.capitalize() for word in slot.split("_"))


def _in_range(value: int | None, level: int, until: int) -> bool:
    return value is not None and level < value <= until


def dungeon_events(
    dungeons: Iterable[Dungeon], faction: str | None, level: int, until: int
) -> list[tuple[int, LookAheadEvent]]:
    events: list[tuple[int, LookAheadEvent]] = []
    for dungeon in dungeons:
        if dungeon.status == "announced" or not _in_range(dungeon.min_level, level, until):
            continue
        if faction is not None and dungeon.access not in (None, faction):
            continue
        levels = f"levels {dungeon.min_level}-{dungeon.max_level}"
        detail = ", ".join(part for part in (levels, dungeon.zone) if part)
        assert dungeon.min_level is not None
        events.append(
            (
                dungeon.min_level,
                LookAheadEvent(
                    kind="dungeon",
                    title=dungeon.name,
                    detail=detail,
                    locked=dungeon.beta_locked,
                    link=f"https://forevercompanion.io/dungeons/{dungeon.id}",
                ),
            )
        )
    return events


def target_events(gear: GearPlan, level: int, until: int) -> list[tuple[int, LookAheadEvent]]:
    upcoming = [u for row in gear.rows for u in row.upcoming]
    upcoming += [u for slot in gear.later for u in slot.upcoming]
    events: list[tuple[int, LookAheadEvent]] = []
    for entry in upcoming:
        if not _in_range(entry.level, level, until):
            continue
        assert entry.level is not None
        target = entry.target
        gain = f"{entry.score_delta:+.1f} score" if entry.score_delta is not None else None
        detail = " · ".join(part for part in (gain, target.source) if part)
        events.append(
            (
                entry.level,
                LookAheadEvent(
                    kind="target",
                    title=f"{slot_label(target.slot)}: {target.item}",
                    detail=detail or None,
                    pinned=target.pinned,
                    link=entry.target_info.wowhead if entry.target_info else None,
                ),
            )
        )
    return events


def talent_events(
    talents: TalentPlanView, level: int, until: int
) -> list[tuple[int, LookAheadEvent]]:
    """One event per level that grants a point: the plan's talent for that point, or a
    note that the plan has run out."""
    planned: dict[int, tuple[str, int]] = {}  # point number -> (talent, rank it reaches)
    for step in talents.steps:
        for offset in range(step.points):
            planned[step.first_point + offset] = (step.talent, step.rank - step.points + offset + 1)
    first = (points_at(level) or 0) + 1
    last = points_at(until) or 0
    events: list[tuple[int, LookAheadEvent]] = []
    for point in range(first, last + 1):
        at = level_for_point(point)
        talent = planned.get(point)
        title = f"Talent: {talent[0]} rank {talent[1]}" if talent else "Talent point"
        detail = None if talent else "Not in the plan yet"
        events.append((at, LookAheadEvent(kind="talent", title=title, detail=detail)))
    return events


def class_quest_events(
    checklist: ClassQuestChecklist, level: int, until: int
) -> list[tuple[int, LookAheadEvent]]:
    events: list[tuple[int, LookAheadEvent]] = []
    for row in checklist.rows:
        if row.done or not _in_range(row.level, level, until):
            continue
        where = ", ".join(part for part in (row.giver, row.location) if part)
        detail = " · ".join(part for part in (row.reward, where) if part)
        events.append(
            (
                row.level,
                LookAheadEvent(
                    kind="class_quest",
                    title=f"Class quest: {row.name}",
                    detail=detail or None,
                    essential=row.essential,
                ),
            )
        )
    return events


def profession_events(
    professions: ProfessionsView, level: int, until: int
) -> list[tuple[int, LookAheadEvent]]:
    events: list[tuple[int, LookAheadEvent]] = []
    for row in professions.professions:
        rank = row.next_rank
        if rank is None or not _in_range(rank.train_at_level, level, until):
            continue
        short = rank.train_at_skill - (row.skill or 0)
        needs = (
            f"needs {rank.train_at_skill} skill, {short} to go"
            if not rank.skill_ready
            else "skill ready"
        )
        detail = f"cap {rank.max_skill}; {needs}" + (f". {row.note}" if row.note else "")
        events.append(
            (
                rank.train_at_level,
                LookAheadEvent(kind="profession", title=f"{rank.name} {row.name}", detail=detail),
            )
        )
    return events


# Within a level: what opens up first, then what to do there.
ORDER: dict[EventKind, int] = {
    "dungeon": 0,
    "class_quest": 1,
    "profession": 2,
    "target": 3,
    "talent": 4,
}


def look_ahead(
    level: int | None,
    levels: int,
    *,
    faction: str | None,
    dungeons: Iterable[Dungeon],
    gear: GearPlan,
    talents: TalentPlanView,
    class_quests: ClassQuestChecklist,
    professions: ProfessionsView,
) -> LookAhead:
    """The next `levels` levels after `level`, each with what it brings. Empty without
    a level; never past the level cap."""
    if level is None:
        return LookAhead(level=None, levels=levels, groups=[])
    until = min(level + levels, MAX_LEVEL)
    events = [
        *dungeon_events(dungeons, faction, level, until),
        *class_quest_events(class_quests, level, until),
        *profession_events(professions, level, until),
        *target_events(gear, level, until),
        *talent_events(talents, level, until),
    ]
    groups: list[LevelGroup] = []
    for at in range(level + 1, until + 1):
        here = sorted((e for lvl, e in events if lvl == at), key=lambda e: ORDER[e.kind])
        if here:
            groups.append(LevelGroup(level=at, events=here))
    return LookAhead(level=level, levels=levels, groups=groups)
