"""Delete everything stored for the character (#133, ADR 0034).

Blizzard's terms ask that a player's data be deleted on request (§11.3). Every table
holds character data except the shared game-data caches listed in SHARED: those hold
items, dungeons, recipes and talent trees that are the same for every character, and are
pruned after 30 days anyway (#131). Any new table is erased unless it's added to SHARED,
so nothing personal is missed by default.
"""

from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, SQLModel

# Game data shared by every character, and the job leases. Never personal.
SHARED = frozenset(
    {
        "catalogitem",
        "itemicon",
        "companionitem",
        "companiondungeon",
        "companionquest",
        "companionrare",
        "companionclassquest",
        "blizzarditem",
        "recipedata",
        "talenttreedata",
        "spellicon",
        "joblease",
    }
)


def erased_tables() -> list[str]:
    """The tables erase_character empties, children before the tables they point at, so
    foreign keys hold on a database that enforces them (Postgres, #44)."""
    ordered = reversed(SQLModel.metadata.sorted_tables)
    return [table.name for table in ordered if table.name not in SHARED]


def erase_character(session: Session) -> dict[str, int]:
    """Delete every row of character data; return the rows removed per table (non-zero
    only). Settings edited in the app go back to the shipped defaults."""
    removed: dict[str, int] = {}
    for name in erased_tables():
        result: Any = session.exec(delete(SQLModel.metadata.tables[name]))  # pyright: ignore[reportCallIssue, reportArgumentType]
        if count := int(result.rowcount or 0):
            removed[name] = count
    session.commit()
    return removed
