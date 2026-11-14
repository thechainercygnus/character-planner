"""Blizzard data kept at most 30 days (#131, ADR 0034)."""

from datetime import datetime, timedelta
from typing import Any, cast

import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import worker
from character_planner.config import Settings
from character_planner.db import (
    BlizzardItem,
    CatalogItem,
    CraftingRecipe,
    ItemIcon,
    NotificationOutbox,
    NotificationState,
    ProgressHistory,
    RecipeData,
    Snapshot,
    SpellIcon,
    StoredToken,
    TalentTreeData,
    utcnow,
)
from character_planner.items import refresh_catalog
from character_planner.progress import progress
from character_planner.retention import RETAIN, forget_character, prune, stored_slug
from character_planner.scoring import Weights

from .conftest import tracked, tracked_character
from .test_app import fixture
from .test_items import mock_battlenet

NOW = utcnow()
OLD = NOW - RETAIN - timedelta(days=1)  # past the terms' 30 days
RECENT = NOW - timedelta(days=2)


def profile(level: int, name: str = "Brumboldt", surname: str = "Doomlet") -> dict[str, Any]:
    base = cast(dict[str, Any], fixture("profile"))
    return base | {"level": level, "name": name, "surname": surname}


def sync(session: Session, at: datetime, level: int, *, source: str = "api") -> None:
    """One sync's tracked snapshots, as the real sync stores them."""
    for kind, payload in (
        ("profile", profile(level)),
        ("equipment", fixture("equipment")),
        ("statistics", fixture("statistics")),
    ):
        session.add(
            Snapshot(
                character_id=tracked(session),
                source=source,
                kind=kind,
                status=200,
                payload=payload,
                captured_at=at,
            )
        )
    session.commit()


def count(session: Session, model: Any) -> int:
    return len(session.exec(select(model)).all())


def test_old_snapshots_go_and_their_progress_is_archived(engine: Engine) -> None:
    with Session(engine) as session:
        sync(session, OLD - timedelta(days=5), 16)
        sync(session, OLD, 17)
        sync(session, RECENT, 19)
        # The player's own entry, between the two old syncs: kept.
        sync(session, OLD - timedelta(days=2), 15, source="manual")
        result = prune(session, NOW)

        kept = session.exec(select(Snapshot)).all()
        archived = session.exec(select(ProgressHistory)).all()
        view = progress(session, Weights(weights={"Stamina": 1.0}), tracked(session))

    profiles = {(s.source, s.payload["level"]) for s in kept if s.kind == "profile"}
    assert profiles == {("api", 19), ("manual", 15)}
    assert len(kept) == 6
    assert result.deleted["snapshot"] == 6  # two old syncs, three kinds each
    # Only the planner's own numbers are archived: date, level, average item level.
    assert sorted(row.level or 0 for row in archived) == [15, 16, 17]
    assert all(row.item_level is not None for row in archived)
    # Progress: archived points first, then live; the score only on live points.
    # The manual entry keeps its snapshots, so it's a live point too, and live wins.
    assert [p.level for p in view.points] == [16, 15, 17, 19]
    assert [p.gear_score is None for p in view.points] == [True, False, True, False]
    # Level-ups run across the archive and the live points.
    assert [u.level for u in view.level_ups] == [19, 17]


def test_caches_older_than_30_days_go(engine: Engine) -> None:
    rows: list[tuple[Any, dict[str, Any]]] = [
        (CatalogItem, {"name_key": "x", "name": "X", "found": True}),
        (ItemIcon, {"item_id": 1}),
        (RecipeData, {"recipe_id": 1, "profession": "Enchanting", "category": "c", "payload": {}}),
        (CraftingRecipe, {"recipe_id": 1, "profession": "Engineering", "found": True}),
        (BlizzardItem, {"item_id": 1, "found": True}),
        (TalentTreeData, {"key": "index", "payload": {}}),
        (SpellIcon, {"spell_id": 1}),
    ]
    with Session(engine) as session:
        for model, values in rows:
            session.add(model(**values, fetched_at=OLD))
        # A fresh row of one cache, to show only old ones go.
        session.add(ItemIcon(item_id=2, fetched_at=RECENT))
        session.commit()
        result = prune(session, NOW)
        left = {model.__name__: count(session, model) for model, _ in rows}

    assert left == {model.__name__: 0 for model, _ in rows} | {"ItemIcon": 1}
    assert result.deleted["itemicon"] == 1 and result.deleted["catalogitem"] == 1


def test_expired_tokens_old_digests_and_sent_alerts_go(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(StoredToken(id=1, access_token="old", expires_at=NOW.timestamp() - 60))
        session.add(StoredToken(id=2, access_token="fresh", expires_at=NOW.timestamp() + 3600))
        session.add(
            NotificationState(character_id=tracked(session), key="digest", value={}, updated_at=OLD)
        )
        alert: dict[str, Any] = {"destination_id": 1, "kind": "level_up", "payload": {}}
        session.add(NotificationOutbox(**alert, dedupe_key="sent", created_at=OLD, sent_at=OLD))
        session.add(NotificationOutbox(**alert, dedupe_key="failed", created_at=OLD, failed=True))
        session.add(NotificationOutbox(**alert, dedupe_key="pending", created_at=OLD))
        session.add(
            NotificationOutbox(**alert, dedupe_key="new", created_at=RECENT, sent_at=RECENT)
        )
        session.commit()
        prune(session, NOW)
        tokens = [t.id for t in session.exec(select(StoredToken)).all()]
        digests = count(session, NotificationState)
        outbox = sorted(o.dedupe_key for o in session.exec(select(NotificationOutbox)).all())

    assert (tokens, digests) == ([2], 0)
    assert outbox == ["new", "pending"]  # not sent yet: still to deliver


def test_a_character_blizzard_no_longer_has_is_forgotten(engine: Engine) -> None:
    with Session(engine) as session:
        sync(session, RECENT, 19)
        sync(session, RECENT - timedelta(hours=1), 18, source="manual")
        me = tracked_character(session)
        session.add(ProgressHistory(character_id=me.id, captured_at=OLD, level=12))
        session.add(NotificationState(character_id=me.id, key="digest", value={}))
        session.commit()
        assert stored_slug(session, me.id) == "brumboldt-doomlet"

        # Renamed or mistyped: a 404 for another name never deletes this history.
        typo = me.model_copy(update={"slug": "brumbolt-doomlet"})
        assert forget_character(session, typo) == 0
        assert count(session, ProgressHistory) == 1

        deleted = forget_character(session, me)
        sources = {s.source for s in session.exec(select(Snapshot)).all()}
        history, digests = count(session, ProgressHistory), count(session, NotificationState)

    assert deleted == 3 + 1 + 1
    assert (sources, history, digests) == ({"manual"}, 0, 0)


@respx.mock
def test_catalog_rows_are_refreshed_after_21_days(settings: Settings, engine: Engine) -> None:
    search = mock_battlenet()
    with Session(engine) as session:
        refresh_catalog(session, settings, ["Dwarven Defender"])
        row = session.exec(select(CatalogItem)).one()
        row.fetched_at = NOW - timedelta(days=22)
        session.add(row)
        session.commit()
        again = refresh_catalog(session, settings, ["Dwarven Defender"])
        refreshed = session.exec(select(CatalogItem)).one()

    assert again.found == ["Dwarven Defender"]  # looked up again, before the prune
    assert refreshed.fetched_at.replace(tzinfo=None) > (NOW - timedelta(days=1)).replace(
        tzinfo=None
    )
    assert search.called  # the icon lookup ran too


def test_the_worker_prunes_daily(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        sync(session, OLD, 17)
        outcome = worker.retention_job(session, settings, None)
    assert outcome == "deleted 3 rows older than 30 days, archived 1 points"
