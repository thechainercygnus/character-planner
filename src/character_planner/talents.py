"""Talent plan: a target build in spending order, compared with the synced talents (ADR 0009).

The Forever talent tree isn't available from any API we use, and it differs from Classic,
so the plan is entered by hand: an ordered list of steps, each "this talent up to this
rank". A talent can appear in several steps (2 ranks now, 3 more later). The specializations
snapshot gives the current ranks; comparing the two gives the next point to spend and
any points spent off plan.

Defaults live in data/curated/talent_plan.yaml; edits from the app are stored in the
database and win over the file, like stat weights (ADR 0005).
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, StringConstraints
from sqlmodel import Session

from character_planner.db import StoredTalentPlan, utcnow
from character_planner.talent_trees import ClassTree, PlanPoint, check_plan
from character_planner.views import Specialization

# Classic rules, matched by the synced data (9 points at level 18): the first talent
# point comes at level 10, then one per level.
FIRST_TALENT_LEVEL = 10


class PlanStep(BaseModel):
    talent: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    rank: int = Field(ge=1, le=10)  # Classic tops out at 5; Forever may differ
    # The talent's id in Blizzard's trees (#88). Plans from before #88 have names only;
    # with_talent_ids fills these in from the trees.
    talent_id: int | None = Field(default=None, gt=0)


class TalentPlan(BaseModel):
    spec: str
    steps: list[PlanStep] = []


class StepStatus(BaseModel):
    talent: str
    talent_id: int | None = None
    rank: int  # target rank after this step
    points: int  # points this step adds
    current: int  # current rank of the talent
    state: Literal["done", "partial", "pending"]
    first_point: int  # overall position of this step's first point (1-based)
    level: int  # level at which this step's last point can be spent


class NextPoint(BaseModel):
    talent: str
    talent_id: int | None = None
    rank: int  # the rank this point takes the talent to
    level: int  # level at which it can be spent


class OffPlan(BaseModel):
    talent: str
    talent_id: int | None = None
    current: int
    planned: int  # 0 when the talent isn't in the plan


class TalentPlanView(BaseModel):
    plan: TalentPlan  # as stored, for editing
    spec: str
    current_spec: str | None
    level: int | None
    available: int | None  # points the level allows
    spent: int | None
    planned_points: int
    steps: list[StepStatus]
    next: NextPoint | None  # first planned point not spent yet
    off_plan: list[OffPlan]
    customised: bool


def points_at(level: int | None) -> int | None:
    return None if level is None else max(0, level - FIRST_TALENT_LEVEL + 1)


def level_for_point(point: int) -> int:
    """The level at which the n-th talent point (1-based) can be spent."""
    return FIRST_TALENT_LEVEL + point - 1


def load_default_plan(path: Path) -> TalentPlan:
    with path.open(encoding="utf-8") as handle:
        return TalentPlan.model_validate(yaml.safe_load(handle))


def current_plan(session: Session, default: TalentPlan) -> TalentPlan:
    stored = session.get(StoredTalentPlan, 1)
    if stored is None:
        return default
    return TalentPlan.model_validate(stored.plan)


def save_plan(session: Session, plan: TalentPlan) -> None:
    session.merge(StoredTalentPlan(id=1, plan=plan.model_dump(), updated_at=utcnow()))
    session.commit()


def reset_plan(session: Session) -> None:
    stored = session.get(StoredTalentPlan, 1)
    if stored is not None:
        session.delete(stored)
        session.commit()


def compare(
    plan: TalentPlan,
    spec: Specialization | None,
    level: int | None,
    *,
    customised: bool = False,
) -> TalentPlanView:
    synced = spec.talents if spec else []
    # A talent is known by its id when both sides have one (#88), else by its name.
    ids_by_name = {t.name.casefold(): t.talent_id for t in synced if t.talent_id is not None}

    def key_of(name: str, talent_id: int | None) -> str:
        found = talent_id if talent_id is not None else ids_by_name.get(name.casefold())
        return f"id:{found}" if found is not None else f"name:{name.casefold()}"

    current = {key_of(t.name, t.talent_id): t.rank or 0 for t in synced}
    names = {key_of(t.name, t.talent_id): t for t in synced}

    steps: list[StepStatus] = []
    target: dict[str, int] = {}  # running target rank per talent
    next_point: NextPoint | None = None
    position = 0
    for step in plan.steps:
        key = key_of(step.talent, step.talent_id)
        before = target.get(key, 0)
        if step.rank <= before:
            continue  # nothing to add: an earlier step already reaches this rank
        target[key] = step.rank
        have = current.get(key, 0)
        points = step.rank - before
        first = position + 1
        position += points
        if have >= step.rank:
            state = "done"
        elif have > before:
            state = "partial"
        else:
            state = "pending"
        if next_point is None and state != "done":
            # The first unspent point of this step, counted in plan order.
            point = first + max(0, have - before)
            next_point = NextPoint(
                talent=step.talent,
                talent_id=step.talent_id,
                rank=max(have, before) + 1,
                level=level_for_point(point),
            )
        steps.append(
            StepStatus(
                talent=step.talent,
                talent_id=step.talent_id,
                rank=step.rank,
                points=points,
                current=have,
                state=state,
                first_point=first,
                level=level_for_point(position),
            )
        )

    off_plan = [
        OffPlan(
            talent=names[key].name,
            talent_id=names[key].talent_id,
            current=rank,
            planned=target.get(key, 0),
        )
        for key, rank in current.items()
        if rank > target.get(key, 0)
    ]

    return TalentPlanView(
        plan=plan,
        spec=plan.spec,
        current_spec=spec.name if spec else None,
        level=level,
        available=points_at(level),
        spent=spec.spent_points if spec else None,
        planned_points=position,
        steps=steps,
        next=next_point,
        off_plan=off_plan,
        customised=customised,
    )


def with_talent_ids(plan: TalentPlan, tree: ClassTree | None) -> TalentPlan:
    """The plan with each step's talent id filled in from the trees by name (#88), for
    plans written before ids. Steps whose name isn't in the trees keep no id."""
    if tree is None or all(step.talent_id is not None for step in plan.steps):
        return plan
    by_name = {node.name.casefold(): node for _, node in tree.nodes().values()}
    steps = [
        step
        if step.talent_id is not None or (node := by_name.get(step.talent.casefold())) is None
        else step.model_copy(update={"talent_id": node.talent_id, "talent": node.name})
        for step in plan.steps
    ]
    return plan.model_copy(update={"steps": steps})


def plan_problems(plan: TalentPlan, tree: ClassTree | None) -> list[str]:
    """What's wrong with a plan against the trees (#88); nothing to say without them."""
    if tree is None:
        return []
    plan = with_talent_ids(plan, tree)
    unknown = [step.talent for step in plan.steps if step.talent_id is None]
    if unknown:
        return [f"Not in the {tree.class_name} talent trees: {', '.join(unknown)}"]
    return check_plan(
        [
            PlanPoint(talent_id=step.talent_id, rank=step.rank)
            for step in plan.steps
            if step.talent_id
        ],
        tree,
    )
