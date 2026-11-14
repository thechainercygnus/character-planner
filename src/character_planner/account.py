"""The logged-in Battle.net account's characters (#15): pick one to track.

Read from GET /profile/user/wow, which needs the user's login token (ADR 0027). The list
is fetched each time it's shown and never stored: it names every character on the
account, and only the ones picked are tracked (ADR 0034).

Field names come from a real response (tests/fixtures/forever_account.json, redacted).
Forever has no realms: a character's href carries its slug and region.
"""

import re
from typing import Any

from pydantic import BaseModel

from character_planner import fields

# https://us.api.blizzard.com/profile/wow/character/brumboldt-doomlet?namespace=...
HREF = re.compile(
    r"^https://(?P<region>[a-z]{2})\.api\.blizzard\.com/profile/wow/character/(?P<slug>[^/?]+)"
)


class AccountCharacter(BaseModel):
    blizzard_id: int | None
    name: str
    surname: str
    slug: str  # Forever's route key, from the href: name-surname, lowercase
    region: str
    character_class: str | None
    race: str | None
    faction: str | None  # ALLIANCE or HORDE
    level: int | None
    tracked: bool = False


def parse_account(payload: Any) -> list[AccountCharacter]:
    """Every character on every WoW account in the response, highest level first."""
    found: list[AccountCharacter] = []
    for account in fields.as_list(fields.get(payload, "wow_accounts")):
        for entry in fields.as_list(fields.get(account, "characters")):
            name = fields.name(fields.get(entry, "name"))
            if not name:
                continue
            surname = fields.name(fields.get(entry, "surname")) or ""
            href = fields.get(entry, "character", "href")
            match = HREF.match(href) if isinstance(href, str) else None
            faction = fields.get(entry, "faction", "type")
            found.append(
                AccountCharacter(
                    blizzard_id=fields.as_int(fields.get(entry, "id")),
                    name=name,
                    surname=surname,
                    slug=match["slug"] if match else f"{name}-{surname}".lower(),
                    region=match["region"] if match else "",
                    character_class=fields.name(fields.get(entry, "playable_class", "name")),
                    race=fields.name(fields.get(entry, "playable_race", "name")),
                    faction=faction if isinstance(faction, str) else None,
                    level=fields.as_int(fields.get(entry, "level")),
                )
            )
    return sorted(found, key=lambda c: (-(c.level or 0), c.name))
