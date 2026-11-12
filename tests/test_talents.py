import json

from character_planner.talents import (
    PlanStep,
    TalentPlan,
    compare,
    level_for_point,
    load_default_plan,
    points_at,
)
from character_planner.views import Specialization, Talent, parse_specialization

from .conftest import FIXTURES, REPO_ROOT

# The synced Brumboldt: Shield Specialization 5, Anticipation 1, Improved Revenge 3 (9 points).
SPEC = parse_specialization(
    json.loads((FIXTURES / "forever_specializations.json").read_text(encoding="utf-8"))
)


def plan(*steps: tuple[str, int]) -> TalentPlan:
    return TalentPlan(spec="Protection", steps=[PlanStep(talent=t, rank=r) for t, r in steps])


BUILD = plan(
    ("Shield Specialization", 5),
    ("Anticipation", 1),
    ("Improved Revenge", 3),
    ("Deflection", 2),
    ("Anticipation", 5),
)


def test_points_by_level() -> None:
    assert [points_at(level) for level in (None, 9, 10, 18)] == [None, 0, 1, 9]
    assert [level_for_point(n) for n in (1, 9, 10)] == [10, 18, 19]


def test_compares_the_synced_talents_with_the_plan() -> None:
    view = compare(BUILD, SPEC, 18)

    assert (view.current_spec, view.available, view.spent, view.planned_points) == (
        "Protection",
        9,
        9,
        15,
    )
    assert [(s.talent, s.state, s.points, s.first_point, s.level) for s in view.steps] == [
        ("Shield Specialization", "done", 5, 1, 14),
        ("Anticipation", "done", 1, 6, 15),
        ("Improved Revenge", "done", 3, 7, 18),
        ("Deflection", "pending", 2, 10, 20),
        ("Anticipation", "pending", 4, 12, 24),
    ]
    assert view.next is not None
    assert (view.next.talent, view.next.rank, view.next.level) == ("Deflection", 1, 19)
    assert view.off_plan == []


def test_partly_spent_step_points_at_the_next_rank() -> None:
    spec = Specialization(
        name="Protection",
        spent_points=3,
        talents=[Talent(name="Deflection", rank=1), Talent(name="Anticipation", rank=2)],
    )
    view = compare(plan(("Anticipation", 2), ("Deflection", 3)), spec, 12)
    assert [s.state for s in view.steps] == ["done", "partial"]
    assert view.next is not None
    assert (view.next.talent, view.next.rank, view.next.level) == ("Deflection", 2, 13)


def test_points_off_plan_are_listed() -> None:
    view = compare(plan(("Shield Specialization", 3)), SPEC, 18)
    assert {(o.talent, o.current, o.planned) for o in view.off_plan} == {
        ("Shield Specialization", 5, 3),
        ("Anticipation", 1, 0),
        ("Improved Revenge", 3, 0),
    }


def test_names_match_case_insensitively_and_redundant_steps_are_skipped() -> None:
    view = compare(plan(("shield specialization", 5), ("Shield Specialization", 2)), SPEC, 18)
    assert len(view.steps) == 1
    assert view.steps[0].state == "done"


def test_without_synced_talents_everything_is_pending() -> None:
    view = compare(BUILD, None, None)
    assert view.current_spec is None
    assert view.available is None
    assert {s.state for s in view.steps} == {"pending"}
    assert view.next is not None
    assert (view.next.talent, view.next.rank, view.next.level) == ("Shield Specialization", 1, 10)


def test_whitespace_is_trimmed_from_talent_names() -> None:
    assert PlanStep(talent="  Deflection ", rank=1).talent == "Deflection"


def test_shipped_plan_matches_the_synced_build() -> None:
    default = load_default_plan(REPO_ROOT / "data" / "curated" / "talent_plan.yaml")
    view = compare(default, SPEC, 18)
    assert view.planned_points == 9
    assert view.next is None
    assert view.off_plan == []
