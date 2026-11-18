"""Game data from the CharacterPlannerExport addon (#177, ADR 0047).

`read_export` turns an uploaded SavedVariables file into typed data, following
`addon/SCHEMA.md`. The file is parsed by `savedvariables`, which never executes it, then
checked strictly against the schema version it declares: a missing field, a wrong type
or an unknown version rejects the whole file. Unknown keys are ignored, so the addon can
keep fields of its own.

`import_for` stores it for the character the upload names, once the file agrees with
that character (#184): only the newest import is kept, beside the Battle.net data and
never over it.

The file carries item ids only (ADR 0047). `view` names them from the shared catalogs:
Forever Companion's items, then Blizzard's (#185). `fetch_item_names` looks up the ids
neither has, in Blizzard's item data, after an import.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Final

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import as_utc, parse_item
from character_planner.config import Settings
from character_planner.db import (
    BlizzardItem,
    Character,
    CompanionItem,
    GameDataImport,
    save_now,
    utcnow,
)
from character_planner.retention import REFRESH_AFTER
from character_planner.savedvariables import LIMITS, LuaValue, SavedVariablesError, parse
from character_planner.tokens import CredentialsError, app_token

logger = logging.getLogger(__name__)

TABLE: Final = "CharacterPlannerExportDB"  # the addon's per-character saved variable
SCHEMA_VERSIONS: Final = (1,)


class GameDataError(ValueError):
    """The upload isn't a CharacterPlannerExport file this planner can read."""


def _list(value: Any) -> Any:
    """An empty Lua table reads as a dict: where the schema wants a list, it's an empty
    list."""
    return [] if value == {} else value


type LuaList[T] = Annotated[list[T], BeforeValidator(_list)]


class _Model(BaseModel):
    # Strict: a string where a number belongs is an error, not a conversion. Unknown keys
    # are ignored; names are the schema's camelCase, read through aliases.
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True, frozen=True)


class Item(_Model):
    container: int
    slot: int = Field(ge=1)
    item_id: int = Field(alias="itemId", ge=1)
    count: int = Field(ge=1)
    quality: int = Field(ge=0, le=8)


class Items(_Model):
    captured_at: int = Field(alias="capturedAt", ge=0)
    items: LuaList[Item]


class Objective(_Model):
    text: str
    type: str
    done: int = Field(ge=0)
    needed: int = Field(ge=0)
    finished: bool


class Quest(_Model):
    quest_id: int = Field(alias="questId", ge=1)
    title: str
    complete: bool
    objectives: LuaList[Objective]


class Quests(_Model):
    captured_at: int = Field(alias="capturedAt", ge=0)
    log: LuaList[Quest]
    completed: LuaList[Annotated[int, Field(ge=1)]] = []


class CharacterInfo(_Model):
    name: str = Field(min_length=1)
    surname: str | None = None
    level: int = Field(ge=1)
    region: str | None = None
    realm: str | None = None


class GameData(_Model):
    """Schema version 1 (`addon/SCHEMA.md`)."""

    schema_version: int = Field(alias="schemaVersion")
    addon_version: str = Field(alias="addonVersion")
    captured_at: int = Field(alias="capturedAt", ge=0)
    character: CharacterInfo
    bags: Items | None = None
    bank: Items | None = None  # None: the bank hasn't been opened since the addon loaded
    quests: Quests | None = None


def _where(error: ValidationError) -> str:
    """The first few problems, by field path: never the values, which are the file's."""
    problems = [
        f"{'.'.join(str(part) for part in e['loc']) or 'the table'}: {e['msg']}"
        for e in error.errors()[:3]
    ]
    more = error.error_count() - len(problems)
    return "; ".join(problems) + (f" (and {more} more)" if more > 0 else "")


def read_export(data: bytes) -> GameData:
    """The addon's data in an uploaded SavedVariables file, checked against its schema."""
    try:
        variables = parse(data, LIMITS)
    except SavedVariablesError as error:
        raise GameDataError(f"Couldn't read the file: {error}") from None
    table: LuaValue = variables.get(TABLE)
    if not isinstance(table, dict):
        raise GameDataError(
            f"No {TABLE} table in this file: upload CharacterPlannerExport.lua, from the "
            "character's SavedVariables folder"
        )
    version = table.get("schemaVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise GameDataError("The file has no schemaVersion: is the addon up to date?")
    if version not in SCHEMA_VERSIONS:
        newer = version > max(SCHEMA_VERSIONS)
        raise GameDataError(
            f"The file uses schema version {version}, which this planner doesn't know"
            + (": update the planner." if newer else ".")
        )
    try:
        return GameData.model_validate(table)
    except ValidationError as error:
        message = f"The file doesn't match schema version {version}: {_where(error)}"
        raise GameDataError(message) from None


# --- storing an import (#184) ---------------------------------------------------------------


class WrongCharacter(GameDataError):
    """The file is another character's: nothing is stored."""


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def check_character(character: Character, data: GameData) -> None:
    """The file must agree with the character it's uploaded for (ADR 0047): the name, and
    the surname and region where the file has them."""
    file = data.character
    wanted = f"{character.name} {character.surname}".strip()
    if not _same(file.name, character.name):
        raise WrongCharacter(f"This file is {file.name}'s, not {wanted}'s: pick {file.name}")
    if file.surname and character.surname and not _same(file.surname, character.surname):
        raise WrongCharacter(f"This file is {file.name} {file.surname}'s, not {wanted}'s")
    if file.region and not _same(file.region, character.region):
        raise WrongCharacter(
            f"This file is from the {file.region.upper()} region; "
            f"{wanted} is {character.region.upper()}"
        )


def _moment(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def import_for(session: Session, character: Character, upload: bytes) -> GameDataImport:
    """Read the upload, check it's this character's, and keep it as their newest import.
    Raises GameDataError (WrongCharacter among them) and stores nothing then."""
    assert character.id is not None
    data = read_export(upload)
    check_character(character, data)
    row = stored(session, character.id) or GameDataImport(
        character_id=character.id,
        schema_version=data.schema_version,
        addon_version=data.addon_version,
        captured_at=_moment(data.captured_at),
        data={},
    )
    row.schema_version = data.schema_version
    row.addon_version = data.addon_version
    row.captured_at = _moment(data.captured_at)
    row.uploaded_at = utcnow()
    row.data = data.model_dump(mode="json")
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("Game data imported for character %s", character.id)
    return row


def stored(session: Session, character_id: int) -> GameDataImport | None:
    return session.exec(
        select(GameDataImport).where(col(GameDataImport.character_id) == character_id)
    ).first()


def remove(session: Session, character_id: int) -> bool:
    row = stored(session, character_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


class SectionAge(BaseModel):
    """When each part was captured in the game: they can differ by days (the bank)."""

    bags: datetime | None
    bank: datetime | None  # None: the bank hasn't been opened since the addon was added
    quests: datetime | None


class ItemInfo(BaseModel):
    """What the app shows for an item id in the file (#185): the file has ids only."""

    name: str | None  # None until a catalog knows it: the app shows "Item <id>"
    quality: str | None  # POOR ... LEGENDARY, as Blizzard names them
    icon_url: str | None  # Forever Companion's items only
    wowhead: str


class GameDataView(BaseModel):
    """A character's imported game data, as the app shows it."""

    imported: bool
    uploaded_at: datetime | None = None
    captured_at: datetime | None = None
    addon_version: str | None = None
    captured: SectionAge | None = None
    data: GameData | None = None  # by field name: bags.items[].item_id, ...
    items: dict[int, ItemInfo] = {}  # every item id in bags and bank


def view(session: Session, character_id: int) -> GameDataView:
    row = stored(session, character_id)
    if row is None:
        return GameDataView(imported=False)
    data = GameData.model_validate(row.data)
    return GameDataView(
        imported=True,
        uploaded_at=as_utc(row.uploaded_at),
        captured_at=as_utc(row.captured_at),
        addon_version=row.addon_version,
        captured=SectionAge(
            bags=_moment(data.bags.captured_at) if data.bags else None,
            bank=_moment(data.bank.captured_at) if data.bank else None,
            quests=_moment(data.quests.captured_at) if data.quests else None,
        ),
        data=data,
        items=item_details(session, data),
    )


# --- naming the file's items (#185) ---------------------------------------------------------

# Enum.ItemQuality's order (addon/SCHEMA.md), in Blizzard's API names.
QUALITY: Final = ("POOR", "COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "ARTIFACT", "HEIRLOOM")
WOWHEAD_ITEM: Final = "https://www.wowhead.com/forever/item={item_id}"


def item_qualities(data: GameData) -> dict[int, int]:
    """Every item id in the bags and bank, with the quality the game gave it."""
    found: dict[int, int] = {}
    for section in (data.bags, data.bank):
        for item in section.items if section else []:
            found.setdefault(item.item_id, item.quality)
    return found


def item_details(session: Session, data: GameData) -> dict[int, ItemInfo]:
    qualities = item_qualities(data)
    if not qualities:
        return {}
    ids = list(qualities)
    companion = {
        row.item_id: info
        for row in session.exec(select(CompanionItem).where(col(CompanionItem.item_id).in_(ids)))
        if row.found and (info := parse_item(row.payload)) is not None
    }
    blizzard = {
        row.item_id: row.payload
        for row in session.exec(select(BlizzardItem).where(col(BlizzardItem.item_id).in_(ids)))
        if row.found
    }
    details: dict[int, ItemInfo] = {}
    for item_id, quality in qualities.items():
        info = companion.get(item_id)
        name = info.name if info else None
        name = name or fields.name(fields.get(blizzard.get(item_id), "name"))
        details[item_id] = ItemInfo(
            name=name,
            quality=QUALITY[quality] if quality < len(QUALITY) else None,
            icon_url=info.icon_url if info else None,
            wowhead=(info.wowhead if info else None) or WOWHEAD_ITEM.format(item_id=item_id),
        )
    return details


def unnamed_item_ids(session: Session, character_id: int) -> list[int]:
    """The import's items no catalog names, and Blizzard hasn't been asked about in the
    last REFRESH_AFTER (a 404 counts as asked)."""
    view_ = view(session, character_id)
    cutoff = utcnow() - REFRESH_AFTER
    unnamed: list[int] = []
    for item_id, info in view_.items.items():
        if info.name is not None:
            continue
        asked = session.get(BlizzardItem, item_id)
        if asked is None or as_utc(asked.fetched_at) < cutoff:
            unnamed.append(item_id)
    return sorted(unnamed)


class NameLookup(BaseModel):
    fetched: int = 0
    errors: list[str] = []


def fetch_item_names(
    session: Session, settings: Settings, item_ids: list[int], http: httpx.Client | None = None
) -> NameLookup:
    """Blizzard's GET /data/wow/item/{id} for each id, into the shared BlizzardItem cache
    (crafted gear's, ADR 0031). Best effort: errors are returned, never raised."""
    outcome = NameLookup()
    if not item_ids:
        return outcome
    try:
        token = app_token(session, settings, http)
    except (httpx.HTTPError, CredentialsError) as error:
        outcome.errors.append(f"Blizzard token: {error}")
        return outcome
    with BlizzardClient(settings, token, http=http) as client:
        for item_id in item_ids:
            result = client.get("item", f"/data/wow/item/{item_id}", settings.static_namespace)
            if result.status not in (200, 404):
                outcome.errors.append(f"item {item_id}: HTTP {result.status}")
                continue
            found = result.status == 200
            save_now(
                session,
                BlizzardItem(
                    item_id=item_id,
                    found=found,
                    payload=result.body if found else None,
                    fetched_at=utcnow(),
                ),
            )
            outcome.fetched += 1
    logger.info("Game data: looked up %d item names", outcome.fetched)
    return outcome
