"""Game data from the CharacterPlannerExport addon (#177, ADR 0047).

`read_export` turns an uploaded SavedVariables file into typed data, following
`addon/SCHEMA.md`. The file is parsed by `savedvariables`, which never executes it, then
checked strictly against the schema version it declares: a missing field, a wrong type
or an unknown version rejects the whole file. Unknown keys are ignored, so the addon can
keep fields of its own.
"""

from typing import Annotated, Any, Final

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from character_planner.savedvariables import LIMITS, LuaValue, SavedVariablesError, parse

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
