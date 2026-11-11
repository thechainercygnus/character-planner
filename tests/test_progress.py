import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.db import Snapshot
from character_planner.progress import build_progress, progress, sync_batches
from character_planner.scoring import Weights

from .conftest import FIXTURES

WEIGHTS = Weights(weights={"Stamina": 1.0, "Armor": 0.1})
T0 = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)


def payload(kind: str) -> Any:
    return json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))


def sync(at: datetime, **payloads: Any) -> list[Snapshot]:
    """One sync: a snapshot per kind, a few milliseconds apart like the real thing."""
    return [
        Snapshot(
            source="api",
            kind=kind,
            status=200,
            payload=body,
            captured_at=at + timedelta(milliseconds=index),
        )
        for index, (kind, body) in enumerate(payloads.items())
    ]


def later_sync() -> dict[str, Any]:
    """Level 19, more health, and the militia belt swapped for Kindlegem Girdle."""
    profile = payload("profile") | {"level": 19}
    statistics = payload("statistics") | {"health": 600}
    equipment = copy.deepcopy(payload("equipment"))
    belt = next(i for i in equipment["equipped_items"] if i["slot"]["type"] == "WAIST")
    belt.update(
        item={"id": 270230},
        name="Kindlegem Girdle",
        level={"value": 18},
        armor={"value": 100, "display": {"display_string": "100 Armor"}},
    )
    return {"profile": profile, "equipment": equipment, "statistics": statistics}


def first_sync() -> dict[str, Any]:
    return {k: payload(k) for k in ("profile", "equipment", "statistics")}


def test_snapshots_close_together_form_one_sync() -> None:
    snaps = sync(T0, **first_sync()) + sync(T0 + timedelta(hours=2), **later_sync())
    batches = sync_batches(reversed(snaps))  # any input order
    assert [sorted(b) for b in batches] == [["equipment", "profile", "statistics"]] * 2


def test_points_gear_changes_and_level_ups() -> None:
    snaps = sync(T0, **first_sync()) + sync(T0 + timedelta(hours=2), **later_sync())
    result = build_progress(snaps, WEIGHTS)

    first, second = result.points
    assert (first.level, first.health, first.stamina, first.armor) == (18, 538, 55, 1105)
    assert first.item_level == 14.6
    assert (second.level, second.health) == (19, 600)
    assert second.item_level == 14.9  # belt 14 -> 18 across 12 pieces
    assert second.gear_score is not None and first.gear_score is not None
    assert round(second.gear_score - first.gear_score, 2) == 2.7  # 27 armor x 0.1

    (change,) = result.gear_changes
    assert (change.slot, change.before, change.after) == (
        "WAIST",
        "Belt of the People's Militia",
        "Kindlegem Girdle",
    )
    assert (change.item_level_before, change.item_level_after, change.score_change) == (14, 18, 2.7)
    assert [(u.level, u.captured_at) for u in result.level_ups] == [(19, second.captured_at)]


def test_a_partial_sync_keeps_the_last_known_equipment() -> None:
    snaps = sync(T0, **first_sync()) + sync(
        T0 + timedelta(hours=1), profile=payload("profile") | {"level": 19}
    )
    result = build_progress(snaps, WEIGHTS)
    assert [p.level for p in result.points] == [18, 19]
    assert result.points[1].item_level == result.points[0].item_level
    assert result.gear_changes == []


def test_no_snapshots_no_progress() -> None:
    result = build_progress([], WEIGHTS)
    assert (result.points, result.gear_changes, result.level_ups) == ([], [], [])


def test_reads_successful_snapshots_from_the_database(engine: Engine) -> None:
    failed = Snapshot(source="api", kind="profile", status=404, payload={}, captured_at=T0)
    with Session(engine) as session:
        session.add_all([*sync(T0, **first_sync()), failed])
        session.add(
            Snapshot(source="api", kind="appearance", status=200, payload={}, captured_at=T0)
        )
        session.commit()
        result = progress(session, WEIGHTS)
    assert len(result.points) == 1
    assert result.points[0].level == 18
