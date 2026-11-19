"""The character's level for planning: the newest of the last sync and the game data
(#186, ADR 0052).

Battle.net's profile updates some time after you play; the addon's file has the level as of
its capture. Whichever was captured later wins, and the planner says which it used. A file
captured before the last sync can't outvote it.
"""

from sqlmodel import Session

from character_planner.companion import as_utc
from character_planner.db import latest_by_kind
from character_planner.gamedata import GameData, stored
from character_planner.views import LevelSource, character_level


def effective_level(session: Session, character_id: int | None) -> LevelSource | None:
    """The newer of the last synced profile's level and the newest import's; None with
    neither."""
    if character_id is None:
        return None
    synced: LevelSource | None = None
    profile = latest_by_kind(session, character_id).get("profile")
    level = character_level(profile.payload if profile else None)
    if profile is not None and level is not None:
        synced = LevelSource(level=level, source="battle.net", at=as_utc(profile.captured_at))
    row = stored(session, character_id)
    if row is None:
        return synced
    game = LevelSource(
        level=GameData.model_validate(row.data).character.level,
        source="game",
        at=as_utc(row.captured_at),
    )
    if synced is None or synced.at is None or (game.at is not None and game.at > synced.at):
        return game
    return synced


def planning_level(session: Session, character_id: int | None) -> int | None:
    found = effective_level(session, character_id)
    return found.level if found else None
