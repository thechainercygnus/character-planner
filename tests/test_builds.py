"""Builds (#216, ADR 0060): a per-character choice that sets its weight preset, talent plan
and guild role together, each still editable, and shown as customised once changed."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from character_planner.classes import load_class_defaults, supported_classes
from character_planner.talent_trees import PlanPoint, check_plan, parse_class_tree, spec_ids
from character_planner.talents import load_default_plan

from .conftest import FIXTURES, REPO_ROOT
from .test_app import client  # noqa: F401 (the client fixture)
from .test_guild import Player, guild_app, players  # noqa: F401

CURATED = REPO_ROOT / "data" / "curated"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def warrior_tree() -> Any:
    payload = fixture("talent_tree_1117.json")
    specs = {sid: fixture(f"talent_tree_1117_spec_{sid}.json") for sid, _ in spec_ids(payload)}
    return parse_class_tree("Warrior", 1117, payload, specs)


@pytest.mark.parametrize("playable", supported_classes(CURATED), ids=lambda c: c.key)
def test_every_class_ships_builds_with_a_preset_and_a_role(playable: Any) -> None:
    defaults = load_class_defaults(CURATED, playable.key)
    assert defaults.builds, f"{playable.name} ships no builds"
    for build in defaults.builds:
        assert defaults.presets.get(build.preset) is not None
        assert build.role in ("tank", "healer", "dps")
    # Each preset is some build's: every class's presets became builds.
    assert {p.key for p in defaults.presets.presets} == {b.preset for b in defaults.builds}


def test_the_warriors_talent_orders_fit_forevers_trees() -> None:
    tree = warrior_tree()
    defaults = load_class_defaults(CURATED, "warrior")
    for build in defaults.builds:
        assert build.talents is not None, build.key
        points = [PlanPoint(talent_id=s.talent_id or 0, rank=s.rank) for s in build.talents.steps]
        assert check_plan(points, tree) == [], build.key
        spent: dict[int, int] = {}
        for step in build.talents.steps:
            spent[step.talent_id or 0] = step.rank
        assert sum(spent.values()) == 51, build.key  # every point by level 60
    # The Protection order starts with the points the character already spent.
    shipped = load_default_plan(CURATED / "talent_plan.yaml")
    protection = defaults.build("protection-leveling")
    assert protection is not None and protection.talents is not None
    first = [(s.talent_id, s.rank) for s in protection.talents.steps[: len(shipped.steps)]]
    assert first == [(s.talent_id, s.rank) for s in shipped.steps]


def test_a_build_that_names_no_preset_fails_loudly(tmp_path: Path) -> None:
    classes = tmp_path / "classes"
    classes.mkdir()
    text = (CURATED / "classes" / "mage.yaml").read_text(encoding="utf-8")
    (classes / "mage.yaml").write_text(text.replace("preset: mage-dungeon", "preset: nope"))
    for name in ("recommend.yaml",):
        (tmp_path / name).write_text((CURATED / name).read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="names no preset nope"):
        load_class_defaults(tmp_path, "mage")


def test_picking_a_build_sets_its_pieces_and_edits_show(client: TestClient) -> None:  # noqa: F811
    view = client.get("/api/builds").json()
    assert view["class_name"] == "Warrior" and view["current"] is None
    assert [b["key"] for b in view["builds"]] == [
        "protection-leveling",
        "protection-dungeon",
        "arms-leveling",
    ]
    arms = next(b for b in view["builds"] if b["key"] == "arms-leveling")
    assert (arms["role"], arms["preset_name"], arms["talents"], arms["spec"]) == (
        "dps",
        "Solo DPS",
        True,
        "Arms",
    )

    picked = client.put("/api/build", json={"key": "arms-leveling"}).json()
    assert (picked["current"], picked["customised"]) == ("arms-leveling", [])
    assert client.get("/api/weights").json()["preset"] == "solo-dps"
    plan = client.get("/api/talents").json()["plan"]
    assert plan["spec"] == "Arms" and plan["steps"][0]["talent"] == "Improved Heroic Strike"

    # Each piece can still be edited; the build then shows which.
    weights = client.get("/api/weights").json()["weights"]
    client.put("/api/weights", json={"weights": weights | {"Strength": 9.0}})
    assert client.get("/api/builds").json()["customised"] == ["weights"]
    client.put("/api/talents/plan", json={"spec": "Arms", "steps": plan["steps"][:3]})
    assert client.get("/api/builds").json()["customised"] == ["weights", "talents"]

    # Picking it again sets the talents again; the preset's edits are kept, and shown.
    again = client.put("/api/build", json={"key": "arms-leveling"}).json()
    assert again["customised"] == ["weights"]

    # Following none changes nothing else.
    cleared = client.put("/api/build", json={"key": None}).json()
    assert cleared["current"] is None and cleared["customised"] == []
    assert client.get("/api/weights").json()["preset"] == "solo-dps"

    missing = client.put("/api/build", json={"key": "feral-tank"})  # a Druid's
    assert missing.status_code == 404


def test_the_guild_takes_the_builds_role_unless_the_member_picks(
    players: dict[str, Player],  # noqa: F811
) -> None:
    tank = players["tank"]  # a Protection Warrior: a tank by spec
    tank.join()
    role = lambda: next(  # noqa: E731
        m["role"] for m in tank.guild()["members"] if m["character_id"] == tank.id
    )
    assert role() == "tank"
    chosen = tank.client.put("/api/build", json={"key": "arms-leveling"}, headers=tank.headers)
    assert chosen.status_code == 200
    assert role() == "dps"  # the build's role over the spec's
    tank.join(role="healer")
    assert role() == "healer"  # the member's own choice over both
