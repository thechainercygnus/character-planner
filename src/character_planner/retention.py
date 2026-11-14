"""Keep Blizzard data at most 30 days (#131, ADR 0034).

Blizzard's API terms (§2 item 18) cap all data from its APIs at 30 days: refresh at
least every 30 days, keep it no longer. So:

- refreshes treat anything older than REFRESH_AFTER as missing and fetch it again, well
  before it expires;
- prune() deletes every Blizzard-sourced row older than RETAIN, after archiving the
  planner's own numbers from old snapshots (ProgressHistory) so Progress keeps its
  history;
- a character Blizzard no longer has is deleted at once (forget_character).

Forever Companion's data isn't Blizzard's and keeps its own cache ages. Manual snapshots
are the player's own entries and are kept.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.companion import as_utc
from character_planner.db import (
    BlizzardItem,
    CatalogItem,
    Character,
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

logger = logging.getLogger(__name__)

RETAIN = timedelta(days=30)  # the terms' limit
REFRESH_AFTER = timedelta(days=21)  # refetched after this, so nothing in use reaches RETAIN

# Blizzard-sourced caches: (table name, model, when each row was fetched).
CACHES: tuple[tuple[str, Any, Any], ...] = (
    ("catalogitem", CatalogItem, CatalogItem.fetched_at),
    ("itemicon", ItemIcon, ItemIcon.fetched_at),
    ("recipedata", RecipeData, RecipeData.fetched_at),
    ("craftingrecipe", CraftingRecipe, CraftingRecipe.fetched_at),
    ("blizzarditem", BlizzardItem, BlizzardItem.fetched_at),
    ("talenttreedata", TalentTreeData, TalentTreeData.fetched_at),
    ("spellicon", SpellIcon, SpellIcon.fetched_at),
)


class PruneResult(BaseModel):
    archived: int = 0  # progress points saved before their snapshots went
    deleted: dict[str, int] = {}  # table -> rows deleted

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def fresh_since(now: datetime | None = None) -> datetime:
    """Rows fetched before this are refreshed: REFRESH_AFTER ago."""
    return (now or utcnow()) - REFRESH_AFTER


def archive_progress(session: Session, before: datetime) -> int:
    """Save the planner's own numbers (date, level, average item level) for each sync
    older than `before`, so Progress keeps them after the snapshots are deleted. Item
    names, stats and raw responses aren't kept (ADR 0034)."""
    from character_planner.progress import TRACKED_KINDS, build_progress
    from character_planner.scoring import Weights

    rows = session.exec(
        select(Snapshot).where(
            col(Snapshot.kind).in_(TRACKED_KINDS),
            col(Snapshot.status) >= 200,
            col(Snapshot.status) < 300,
        )
    ).all()
    by_character: dict[int | None, list[Snapshot]] = {}
    for row in rows:
        by_character.setdefault(row.character_id, []).append(row)
    archived = 0
    for character_id, own in by_character.items():
        kept = {
            as_utc(row.captured_at)
            for row in session.exec(
                select(ProgressHistory).where(col(ProgressHistory.character_id) == character_id)
            ).all()
        }
        # The score depends on today's weights, so it isn't archived: empty weights will do.
        for point in build_progress(own, Weights(weights={})).points:
            moment = as_utc(point.captured_at)
            if moment >= before or moment in kept:
                continue
            session.add(
                ProgressHistory(
                    character_id=character_id,
                    captured_at=point.captured_at,
                    level=point.level,
                    item_level=point.item_level,
                )
            )
            archived += 1
    return archived


def prune(session: Session, now: datetime | None = None) -> PruneResult:
    """Delete Blizzard-sourced rows older than RETAIN, archiving Progress first."""
    now = now or utcnow()
    cutoff = now - RETAIN
    result = PruneResult(archived=archive_progress(session, cutoff))

    def remove(name: str, statement: Any) -> None:
        if count := _delete(session, statement):
            result.deleted[name] = count

    remove(
        "snapshot",
        delete(Snapshot).where(col(Snapshot.source) == "api", col(Snapshot.captured_at) < cutoff),
    )
    for name, table, fetched_at in CACHES:
        remove(name, delete(table).where(fetched_at < cutoff))
    remove("storedtoken", delete(StoredToken).where(col(StoredToken.expires_at) < now.timestamp()))
    # What alerts compare against, and alerts already sent: both name items and levels.
    remove(
        "notificationstate",
        delete(NotificationState).where(col(NotificationState.updated_at) < cutoff),
    )
    remove(
        "notificationoutbox",
        delete(NotificationOutbox).where(
            col(NotificationOutbox.created_at) < cutoff,
            (col(NotificationOutbox.sent_at).is_not(None)) | col(NotificationOutbox.failed),
        ),
    )
    session.commit()
    if result.total or result.archived:
        logger.info(
            "Retention: deleted %d rows older than 30 days (%s), archived %d progress points",
            result.total,
            ", ".join(f"{name} {count}" for name, count in sorted(result.deleted.items())),
            result.archived,
        )
    return result


def stored_slug(session: Session, character_id: int | None) -> str | None:
    """Who the character's stored snapshots are about: name-surname, lowercased."""
    snapshot = session.exec(
        select(Snapshot)
        .where(
            col(Snapshot.character_id) == character_id,
            col(Snapshot.kind) == "profile",
            col(Snapshot.status) == 200,
        )
        .order_by(col(Snapshot.captured_at).desc())
    ).first()
    payload = snapshot.payload if snapshot else None
    name, surname = fields.get(payload, "name"), fields.get(payload, "surname")
    if not isinstance(name, str):
        return None
    return f"{name}-{surname}".lower() if isinstance(surname, str) else name.lower()


def forget_character(session: Session, character: Character) -> int:
    """Delete a character Blizzard no longer has (§2 item 18): its snapshots, archived
    progress and alert state. Only when its stored data is about that same name, so a
    rename or a typo never deletes a real history. Returns rows deleted."""
    slug = character.slug
    if stored_slug(session, character.id) != slug:
        return 0
    deleted = 0
    for statement in (
        delete(Snapshot).where(
            col(Snapshot.character_id) == character.id, col(Snapshot.source) == "api"
        ),
        delete(ProgressHistory).where(col(ProgressHistory.character_id) == character.id),
        # Alert state is still one set for the instance; per character in #14's next step.
        delete(NotificationState),
    ):
        deleted += _delete(session, statement)
    session.commit()
    logger.warning("Character %s no longer exists on Battle.net: its stored data was deleted", slug)
    return deleted


def _delete(session: Session, statement: Any) -> int:
    """Run a DELETE and return how many rows it removed."""
    result = cast(CursorResult[Any], session.exec(statement))
    return result.rowcount
