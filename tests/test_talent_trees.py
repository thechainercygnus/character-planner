"""Talent trees from Blizzard's game data, and plans checked against them (#88).

The fixtures are real responses from the static-forever-us namespace (2026-11-13): the
talent tree index, the Warlock (1116) and Warrior (1117) class trees and their spec trees,
and the spell media for Improved Life Tap.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import jobs
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import Snapshot, SpellIcon, TalentTreeData
from character_planner.talent_trees import (
    ClassTree,
    PlanPoint,
    check_plan,
    class_tree_id,
    parse_class_tree,
    refresh_talent_trees,
    spec_ids,
    stored_tree,
)
from character_planner.talents import TalentPlan, plan_problems, with_talent_ids
from character_planner.views import parse_specialization

from .conftest import FIXTURES

API = "https://us.api.blizzard.com/data/wow"

# Talent ids from the Warrior's Protection tree.
SHIELD_SPEC, ANTICIPATION, IMPROVED_REVENGE = 135507, 135506, 135500


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def tree_of(class_name: str, tree_id: int) -> ClassTree:
    payload = fixture(f"talent_tree_{tree_id}.json")
    specs = {sid: fixture(f"talent_tree_{tree_id}_spec_{sid}.json") for sid, _ in spec_ids(payload)}
    return parse_class_tree(class_name, tree_id, payload, specs)


WARRIOR = tree_of("Warrior", 1117)
WARLOCK = tree_of("Warlock", 1116)


def store(session: Session, tree_id: int) -> None:
    session.add(TalentTreeData(key="index", payload=fixture("talent_tree_index.json")))
    payload = fixture(f"talent_tree_{tree_id}.json")
    session.add(TalentTreeData(key=f"class:{tree_id}", payload=payload))
    for sid, _ in spec_ids(payload):
        spec = fixture(f"talent_tree_{tree_id}_spec_{sid}.json")
        session.add(TalentTreeData(key=f"spec:{tree_id}:{sid}", payload=spec))
    session.commit()


def profile(session: Session, class_name: str) -> None:
    session.add(
        Snapshot(
            source="api",
            kind="profile",
            status=200,
            payload={"level": 18, "character_class": {"name": class_name, "id": 1}},
        )
    )
    session.commit()


# --- parsing ---------------------------------------------------------------------------------


def test_the_index_names_each_class_tree() -> None:
    index = fixture("talent_tree_index.json")
    assert class_tree_id(index, "Warlock") == 1116
    assert class_tree_id(index, "warrior") == 1117
    assert class_tree_id(index, "Death Knight") is None


def test_spec_trees_are_parsed_with_their_grid_and_ranks() -> None:
    assert [s.name for s in WARLOCK.specs] == ["Affliction", "Demonology", "Destruction"]
    assert [len(s.nodes) for s in WARLOCK.specs] == [17, 19, 16]
    affliction = WARLOCK.specs[0]
    life_tap = affliction.nodes[0]
    assert (life_tap.name, life_tap.row, life_tap.col, life_tap.max_rank) == (
        "Improved Life Tap",
        1,
        1,
        2,
    )
    assert life_tap.ranks[0].startswith("Increases the amount of Mana awarded by your Life Tap")
    assert life_tap.spell_id == 18182


def test_columns_count_from_each_trees_left_edge() -> None:
    """Blizzard counts columns across the class (Protection is 14-17)."""
    for spec in WARRIOR.specs:
        assert min(n.col for n in spec.nodes) == 1, spec.name


def test_prerequisites_become_talent_ids() -> None:
    nodes = WARRIOR.nodes()
    _, mortal_strike = next(v for v in nodes.values() if v[1].name == "Mortal Strike")
    assert [nodes[t][1].name for t in mortal_strike.requires] == ["Sweeping Strikes"]


# --- plans against the trees -------------------------------------------------------------


def test_the_shipped_warrior_plan_fits_the_trees() -> None:
    plan = [
        PlanPoint(talent_id=SHIELD_SPEC, rank=5),
        PlanPoint(talent_id=ANTICIPATION, rank=1),
        PlanPoint(talent_id=IMPROVED_REVENGE, rank=3),
    ]
    assert check_plan(plan, WARRIOR) == []


@pytest.mark.parametrize(
    ("plan", "problem"),
    [
        ([PlanPoint(talent_id=ANTICIPATION, rank=1)], "needs 5 points in Protection first"),
        ([PlanPoint(talent_id=SHIELD_SPEC, rank=6)], "only has 5 ranks"),
        (
            [PlanPoint(talent_id=SHIELD_SPEC, rank=3), PlanPoint(talent_id=SHIELD_SPEC, rank=2)],
            "already at rank 3",
        ),
        ([PlanPoint(talent_id=1, rank=1)], "isn't in the Warrior trees"),
    ],
)
def test_broken_plans_are_explained(plan: list[PlanPoint], problem: str) -> None:
    (found,) = check_plan(plan, WARRIOR)
    assert problem in found and found.startswith("Step ")


def test_a_prerequisite_must_be_maxed_first() -> None:
    nodes = {n.name: n for _, n in WARRIOR.nodes().values()}
    shield, master = nodes["Shield Specialization"], nodes["Master of Defense"]
    assert master.requires == [shield.talent_id]
    # Enough points in Protection for Master of Defense's row, but Shield Specialization
    # only at 4/5.
    fillers = [
        PlanPoint(talent_id=n.talent_id, rank=n.max_rank)
        for n in sorted(WARRIOR.specs[2].nodes, key=lambda n: n.row)
        if n.row < master.row and n.talent_id != shield.talent_id
    ]
    plan = [PlanPoint(talent_id=shield.talent_id, rank=4), *fillers]
    plan.append(PlanPoint(talent_id=master.talent_id, rank=1))
    problems = check_plan(plan, WARRIOR)
    assert any("needs Shield Specialization at 5/5 first" in p for p in problems)


def test_old_plans_get_ids_from_names() -> None:
    plan = TalentPlan(spec="Protection", steps=[{"talent": "anticipation", "rank": 1}])  # type: ignore[list-item]
    with_ids = with_talent_ids(plan, WARRIOR)
    assert (with_ids.steps[0].talent_id, with_ids.steps[0].talent) == (ANTICIPATION, "Anticipation")
    assert plan_problems(
        TalentPlan(spec="x", steps=[{"talent": "Not A Talent", "rank": 1}]),  # type: ignore[list-item]
        WARRIOR,
    ) == ["Not in the Warrior talent trees: Not A Talent"]
    assert plan_problems(plan, None) == []  # no trees yet: nothing to check against


def test_synced_talents_carry_ids_from_every_tree() -> None:
    payload = fixture("forever_specializations.json")
    group = payload["specialization_groups"][0]
    extra = {
        "specialization": {"name": "Arms", "id": 26},
        "specialization_name": "Arms",
        "spent_points": 1,
        "talents": [{"talent": {"name": "Improved Rend", "id": 999}, "talent_rank": 1}],
    }
    group["specializations"].append(extra)
    spec = parse_specialization(payload)
    assert spec is not None
    assert spec.name == "Protection"  # the tree with the most points
    assert spec.spent_points == 10  # 9 in Protection + 1 in Arms
    assert {t.talent_id for t in spec.talents} == {SHIELD_SPEC, ANTICIPATION, IMPROVED_REVENGE, 999}


# --- fetching -------------------------------------------------------------------------------


def mock_blizzard_talents() -> None:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.get(f"{API}/talent-tree/index").mock(
        return_value=httpx.Response(200, json=fixture("talent_tree_index.json"))
    )
    respx.get(f"{API}/talent-tree/1116").mock(
        return_value=httpx.Response(200, json=fixture("talent_tree_1116.json"))
    )
    for sid in (355, 354, 593):
        respx.get(f"{API}/talent-tree/1116/playable-specialization/{sid}").mock(
            return_value=httpx.Response(200, json=fixture(f"talent_tree_1116_spec_{sid}.json"))
        )
    respx.get(url__startswith=f"{API}/media/spell/").mock(
        return_value=httpx.Response(200, json=fixture("spell_media_18182.json"))
    )


@respx.mock
def test_refresh_stores_the_trees_and_icons(engine: Engine, settings: Settings) -> None:
    mock_blizzard_talents()
    with Session(engine) as session:
        result = refresh_talent_trees(session, settings, "Warlock")
        tree = stored_tree(session, "Warlock")
        icons = session.get(SpellIcon, 18182)
    assert (result.trees, result.errors) == (4, [])
    assert result.icons == 52  # one per talent in the three trees
    assert tree is not None and [s.name for s in tree.specs] == [s.name for s in WARLOCK.specs]
    assert icons is not None and icons.url and icons.url.endswith("/136126.jpg")
    assert tree.specs[0].nodes[0].icon_url == icons.url


@respx.mock
def test_icons_not_found_are_tried_again_and_found_ones_are_not(
    engine: Engine, settings: Settings
) -> None:
    mock_blizzard_talents()
    media = respx.get(url__startswith=f"{API}/media/spell/")
    media.mock(return_value=httpx.Response(503))
    with Session(engine) as session:
        assert refresh_talent_trees(session, settings, "Warlock").icons == 0
        media.mock(return_value=httpx.Response(200, json=fixture("spell_media_18182.json")))
        assert refresh_talent_trees(session, settings, "Warlock").icons == 52
        assert refresh_talent_trees(session, settings, "Warlock").icons == 0  # nothing left
    assert media.call_count == 52 * 2


@respx.mock
def test_a_class_without_a_tree_is_reported(engine: Engine, settings: Settings) -> None:
    mock_blizzard_talents()
    with Session(engine) as session:
        result = refresh_talent_trees(session, settings, "Death Knight")
    assert result.errors == ["no talent tree for the class Death Knight"]


# --- the API and first loads ----------------------------------------------------------------


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


def test_missing_data_includes_the_synced_classs_trees(engine: Engine) -> None:
    with Session(engine) as session:
        assert "talents" not in jobs.missing_data(session)  # no class yet
        profile(session, "Warrior")
        assert "talents" in jobs.missing_data(session)
        store(session, 1117)
        assert "talents" not in jobs.missing_data(session)


def test_the_tree_endpoint_waits_for_the_trees(client: TestClient, engine: Engine) -> None:
    assert client.get("/api/talents/tree").json() == {
        "class_name": None,
        "tree": None,
        "loading": False,
    }
    with Session(engine) as session:
        profile(session, "Warrior")
    assert client.get("/api/talents/tree").json()["tree"] is None
    with Session(engine) as session:
        store(session, 1117)
    view = client.get("/api/talents/tree").json()
    assert view["class_name"] == "Warrior"
    assert [s["name"] for s in view["tree"]["specs"]] == ["Arms", "Fury", "Protection"]


def test_saved_plans_are_checked_against_the_trees(client: TestClient, engine: Engine) -> None:
    with Session(engine) as session:
        profile(session, "Warrior")
        store(session, 1117)
    bad = {"spec": "Protection", "steps": [{"talent": "Anticipation", "rank": 1}]}
    response = client.put("/api/talents/plan", json=bad)
    assert response.status_code == 422
    assert "needs 5 points in Protection first" in response.json()["detail"]

    good = {
        "spec": "Protection",
        "steps": [
            {"talent": "Shield Specialization", "rank": 5},
            {"talent": "Anticipation", "rank": 1},
        ],
    }
    saved = client.put("/api/talents/plan", json=good).json()
    assert [s["talent_id"] for s in saved["plan"]["steps"]] == [SHIELD_SPEC, ANTICIPATION]


def test_the_refresh_endpoint_needs_a_synced_character(client: TestClient) -> None:
    assert client.post("/api/talents/refresh").status_code == 409


def test_the_shipped_plan_is_valid_against_the_real_trees() -> None:
    from character_planner.talents import load_default_plan

    plan = load_default_plan(Path("data/curated/talent_plan.yaml"))
    assert [s.talent_id for s in plan.steps] == [SHIELD_SPEC, ANTICIPATION, IMPROVED_REVENGE]
    assert plan_problems(plan, WARRIOR) == []
