"""The addon's schema, version 1 (#183, ADR 0047, addon/SCHEMA.md): what a valid file
reads as, and how a wrong one is refused."""

import re

import pytest

from character_planner.gamedata import GameDataError, read_export

from .conftest import FIXTURES, REPO_ROOT

SAVED = FIXTURES / "savedvariables"
SCHEMA = REPO_ROOT / "addon" / "SCHEMA.md"


def schema_example() -> str:
    """The example in addon/SCHEMA.md: the contract the addon writes to."""
    found = re.search(r"```lua\n(.*?)```", SCHEMA.read_text(encoding="utf-8"), re.S)
    assert found, "addon/SCHEMA.md has a lua example"
    return found.group(1)


def with_db(body: str) -> bytes:
    return f"CharacterPlannerExportDB = {body}".encode()


HEADER = """
    schemaVersion = 1, addonVersion = "0.1.0", capturedAt = 1794700000,
    character = { name = "Lilalx", level = 10 },
"""


def test_the_schema_documents_example_reads_as_documented() -> None:
    data = read_export(schema_example().encode())
    assert data.schema_version == 1
    assert data.character.name == "Brumboldt"
    assert data.character.surname == "Doomlet"
    assert data.character.region == "US"
    assert data.bags is not None and data.bank is not None and data.quests is not None
    (item,) = data.bags.items
    assert (item.container, item.slot, item.item_id, item.count, item.quality) == (0, 1, 6948, 1, 1)
    assert data.bank.items == []  # an empty table where a list belongs: an empty list
    (quest,) = data.quests.log
    assert (quest.quest_id, quest.complete) == (1640, False)
    assert quest.objectives[0].needed == 1
    assert data.quests.completed == [1638, 1639]


def test_a_windows_file_with_a_bom_reads_the_same() -> None:
    from_windows = read_export((SAVED / "example_crlf_bom.lua").read_bytes())
    assert from_windows == read_export(schema_example().encode())


def test_a_real_file_from_the_addon_reads_as_written() -> None:
    """The first real file (addon 0.2.0, 2026-11-18), byte for byte as the game wrote it:
    CRLF, keys in the game's order, the bank not opened yet."""
    data = read_export((SAVED / "real_addon_0.2.0_crlf.lua").read_bytes())
    assert (data.schema_version, data.addon_version) == (1, "0.2.0")
    character = data.character
    assert (character.name, character.surname, character.level, character.region) == (
        "Brumboldt",
        "Doomlet",
        22,
        "US",
    )
    # GetRealmName() on Forever: the server's name, not the WTF folder's "91".
    assert character.realm == "CAMWOW US2 Realm 7 PvE"
    assert data.bags is not None and len(data.bags.items) == 36
    assert {item.container for item in data.bags.items} == {0, 1, 2, 5}
    assert data.bank is None  # not seen yet
    assert data.quests is not None
    assert (len(data.quests.log), len(data.quests.completed)) == (28, 207)
    objectives = [o for quest in data.quests.log for o in quest.objectives]
    assert {o.type for o in objectives} == {"item", "log", "monster", "event", "object"}
    # The game writes most counts into the text, which the quest log relies on (#185).
    assert sum(f"{o.done}/{o.needed}" in o.text for o in objectives) == 31


def test_only_the_header_is_required() -> None:
    data = read_export((SAVED / "minimal_v1.lua").read_bytes())
    assert (data.character.name, data.character.level) == ("Lilalx", 10)
    assert data.character.surname is None and data.character.region is None
    # Nothing recorded yet: unknown, which isn't the same as empty.
    assert data.bags is None and data.bank is None and data.quests is None


def test_unknown_keys_and_other_variables_are_ignored() -> None:
    data = read_export((SAVED / "every_form_v1.lua").read_bytes())
    assert data.bags is not None
    assert [i.item_id for i in data.bags.items] == [6948, 4306, 2589]
    assert data.character.realm == "91"


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (
            "{ " + HEADER.replace("schemaVersion = 1", "schemaVersion = 2") + "}",
            "schema version 2, which this planner doesn't know: update the planner.",
        ),
        (
            "{ " + HEADER.replace("schemaVersion = 1", "schemaVersion = 0") + "}",
            "schema version 0, which this planner doesn't know.",
        ),
        ("{ " + HEADER.replace("schemaVersion = 1,", "") + "}", "no schemaVersion"),
        (
            "{ " + HEADER.replace("schemaVersion = 1", 'schemaVersion = "1"') + "}",
            "no schemaVersion",
        ),
        (
            "{ " + HEADER.replace("level = 10", 'level = "10"') + "}",
            "character.level: Input should be a valid integer",
        ),
        (
            "{ " + HEADER.replace("level = 10", "level = 10.5") + "}",
            "character.level: Input should be a valid integer",
        ),
        ("{ " + HEADER.replace(", level = 10", "") + "}", "character.level: Field required"),
        ("{ " + HEADER.replace('name = "Lilalx"', 'name = ""') + "}", "character.name"),
        (
            "{ " + HEADER + "bags = { capturedAt = 1, items = { { container = 0, slot = 1,"
            " itemId = 6948, count = 0, quality = 1 } } } }",
            "bags.items.0.count: Input should be greater than or equal to 1",
        ),
        ("{ " + HEADER + "bank = { items = {} } }", "bank.capturedAt: Field required"),
        (
            "{ " + HEADER + "quests = { capturedAt = 1, log = { { questId = 1 } } } }",
            "quests.log.0.title: Field required",
        ),
        ("{ " + HEADER + "quests = { capturedAt = 1, log = 'none' } }", "quests.log"),
        ("'not a table'", "No CharacterPlannerExportDB table"),
    ],
)
def test_a_file_that_breaks_the_schema_is_refused(body: str, why: str) -> None:
    with pytest.raises(GameDataError, match=re.escape(why)):
        read_export(with_db(body))


def test_another_addons_file_is_refused_by_name() -> None:
    with pytest.raises(GameDataError, match=r"upload CharacterPlannerExport\.lua"):
        read_export(b'BrotherBags = { ["x"] = {} }')


def test_a_hostile_file_is_refused_before_the_schema() -> None:
    with pytest.raises(GameDataError, match=r"^Couldn't read the file: line 1, column 28"):
        read_export(b'CharacterPlannerExportDB = os.execute("calc")')


def test_errors_list_a_few_problems_and_never_the_values() -> None:
    body = (
        "{ schemaVersion = 1, addonVersion = 7, capturedAt = 'x', "
        "character = { name = 'SECRET-NAME', level = 'y', region = 1 } }"
    )
    with pytest.raises(GameDataError) as caught:
        read_export(with_db(body))
    message = str(caught.value)
    assert "(and 1 more)" in message
    assert "SECRET-NAME" not in message and "'x'" not in message


def test_the_fixtures_are_all_utf8_text() -> None:
    for fixture in SAVED.glob("*.lua"):
        fixture.read_bytes().decode("utf-8")  # the reader assumes UTF-8
