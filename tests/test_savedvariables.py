"""The SavedVariables reader (#183, ADR 0047): the subset it accepts, everything it
refuses, its limits, and property tests for both."""

import contextlib
import math
import re
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from character_planner.savedvariables import (
    Limits,
    LuaValue,
    SavedVariablesError,
    parse,
)

from .conftest import FIXTURES

SAVED = FIXTURES / "savedvariables"


def one(text: str, limits: Limits | None = None) -> LuaValue:
    """The value of `X = <text>`."""
    parsed = parse(f"X = {text}".encode(), limits) if limits else parse(f"X = {text}".encode())
    return parsed["X"]


# --- what it accepts ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1", 1),
        ("-12", -12),
        ("0x1F", 31),
        ("-0X10", -16),
        ("1.5", 1.5),
        (".5", 0.5),
        ("1e3", 1000.0),
        ("2.5E-2", 0.025),
        ("1e+16", 1e16),
        ("true", True),
        ("false", False),
        ("nil", None),
        ('""', ""),
        ("'single'", "single"),
        ('"a\\"b\\\\c"', 'a"b\\c'),
        ('"\\a\\b\\f\\n\\r\\t\\v"', "\a\b\f\n\r\t\v"),
        ('"line\\\nbreak"', "line\nbreak"),
        ('"crlf\\\r\nbreak"', "crlf\nbreak"),  # an escaped line break, Windows style
        ('"\\65\\066\\0677"', "ABC7"),
        ('"\\x41\\u{20AC}"', "A€"),
        ('"skip\\z   \n  spaces"', "skipspaces"),
        ('"café ✓"', "café ✓"),
        ('"\\255"', "�"),  # not UTF-8: shown as U+FFFD
    ],
)
def test_reads_each_scalar(text: str, value: LuaValue) -> None:
    assert one(text) == value


def test_reads_tables_as_lists_or_dicts() -> None:
    assert one("{}") == {}
    assert one("{ 1, 2, 3, }") == [1, 2, 3]
    assert one("{ [1] = 'a'; [2] = 'b' }") == ["a", "b"]
    assert one("{ 'a', [3] = 'c', 'b' }") == ["a", "b", "c"]  # keys 1, 3, 2: still 1..n
    assert one("{ [2] = 'b' }") == {2: "b"}  # doesn't start at 1: a dict
    assert one("{ x = 1, ['y z'] = 2, [true] = 3, [1.5] = 4 }") == {
        "x": 1,
        "y z": 2,
        True: 3,
        1.5: 4,
    }
    assert one("{ [1.0] = 'a' }") == ["a"]  # 1.0 and 1 are the same key in Lua
    assert one("{ a = 1, a = 2 }") == {"a": 2}  # the last one wins, as in Lua
    assert one("{ { { 'deep' } } }") == [[["deep"]]]


def test_reads_statements_comments_and_line_endings() -> None:
    text = (
        "﻿-- a comment\r\nA = 1;\r\n--[[ long\r\n comment ]] B = { 'x' } --[==[ ]] ]==]\r\nC = nil"
    )
    assert parse(text.encode()) == {"A": 1, "B": ["x"], "C": None}
    assert parse(b"") == {}
    assert parse(b"  -- only a comment\n") == {}


def test_reads_every_form_in_one_file() -> None:
    parsed = parse((SAVED / "every_form_v1.lua").read_bytes())
    assert parsed["OtherAddonSetting"] == "kept but ignored"
    table: Any = parsed["CharacterPlannerExportDB"]
    assert table["capturedAt"] == 0x6AFA3BE0
    assert table["character"]["surname"] == "Doomlet"
    assert table["character"]["realm"] == "91"
    assert [item["itemId"] for item in table["bags"]["items"]] == [6948, 4306, 2589]
    assert table["quests"]["log"][0]["title"] == 'Quote "inside", tab\tand a back\\slash'


# --- what it refuses -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        # Code, in all the forms a hostile file might try: nothing is ever run.
        ('X = os.execute("calc")', "expected a value, found 'os'"),
        ("X = loadstring('return 1')()", "expected a value, found 'loadstring'"),
        ("X = function() end", "expected a value, found 'function'"),
        ("X = 1 + 1", "expected a variable name, found '+'"),
        ("X = 'a' .. 'b'", "expected a variable name, found '.'"),
        ("X = { [os.time()] = 1 }", "expected a value, found 'os'"),
        ("X = setmetatable({}, {})", "expected a value, found 'setmetatable'"),
        ("X = Y", "expected a value, found 'Y'"),
        ("X = #{}", "expected a value, found '#'"),
        # Not numbers.
        ("X = inf", "expected a value, found 'inf'"),
        ("X = -inf", "expected a number"),
        ("X = 1e400", "out of range"),
        ("X = 12abc", "expected a number"),
        ("X = 1.2.3", "isn't a number"),
        ("X = 0x", "needs digits"),
        ("X = -", "isn't a number"),
        # Broken structure.
        ("X = { 1, 2", "expected ',' or '}', found the end of the file"),
        ("X = { 1 2 }", "expected ',' or '}'"),
        ("X = { [{}] = 1 }", "a table key must be"),
        ("X = { [nil] = 1 }", "a table key must be"),
        ("X =", "expected a value, found the end of the file"),
        ("= 1", "expected a variable name"),
        ("nil = 1", "expected a variable name"),
        ("X = [[long string]]", "expected a value, found '['"),
        ("--[[ never closed", "a long comment is never closed"),
        # Broken strings.
        ('X = "never closed', "a string is never closed"),
        ('X = "ends in a backslash\\', "a string is never closed"),
        ('X = "line\nbreak"', "a line break inside a string"),
        ('X = "\\q"', "an unknown escape \\q"),
        ('X = "\\x4"', "\\x needs two hexadecimal digits"),
        ('X = "\\256"', "a decimal escape above 255"),
        ('X = "\\u{D800}"', "isn't a character"),
        ('X = "\\u{}"', "needs hexadecimal digits"),
    ],
)
def test_refuses_anything_outside_the_subset(text: str, why: str) -> None:
    with pytest.raises(SavedVariablesError, match=re.escape(why)):
        parse(text.encode())


def test_errors_name_the_line_and_column() -> None:
    with pytest.raises(SavedVariablesError, match=r"^line 3, column 7: expected a value"):
        parse(b"A = 1\nB = {\n  x = os.exit(),\n}")


def test_errors_never_echo_the_file() -> None:
    secret = "a" * 500
    with pytest.raises(SavedVariablesError) as caught:
        parse(f"X = {secret}".encode())
    assert len(str(caught.value)) < 100


def test_refuses_what_isnt_utf8_text() -> None:
    with pytest.raises(SavedVariablesError, match="not UTF-8"):
        parse(b"X = '\xff\xfe'")
    with pytest.raises(SavedVariablesError, match="NUL"):
        parse(b"X = 1\x00")


# --- limits ------------------------------------------------------------------------------------


def test_limits_hold() -> None:
    small = Limits(max_bytes=100, max_depth=3, max_values=5, max_string=8, max_number=6)
    with pytest.raises(SavedVariablesError, match="larger than 100 bytes"):
        parse(b"X = 1" + b" " * 100, small)
    assert one("{{{1}}}", small) == [[[1]]]
    with pytest.raises(SavedVariablesError, match="nested more than 3 deep"):
        one("{{{{1}}}}", small)
    with pytest.raises(SavedVariablesError, match="more than 5 values"):
        one("{1, 2, 3, 4, 5}", small)
    assert one('"12345678"', small) == "12345678"
    with pytest.raises(SavedVariablesError, match="longer than 8 bytes"):
        one('"123456789"', small)
    with pytest.raises(SavedVariablesError, match="longer than 8 bytes"):
        one('"\\u{20AC}\\u{20AC}\\u{20AC}"', small)  # 9 bytes once escapes are read
    with pytest.raises(SavedVariablesError, match="longer than 6 characters"):
        one("1234567", small)


def test_the_default_limits_take_a_full_character_with_room_to_spare() -> None:
    """ADR 0047: about 160 bag slots and a few hundred bank slots come to ~100 KiB."""
    item = "{ container = 0, slot = 1, itemId = 6948, count = 1, quality = 1 },\n"
    text = "X = {\n" + item * 4000 + "}"  # ten times a full bank and bags
    assert len(text) < 1024 * 1024
    value = one(text[4:])
    assert isinstance(value, list) and len(value) == 4000


def test_a_deep_hostile_file_fails_cleanly() -> None:
    with pytest.raises(SavedVariablesError, match="nested more than 16 deep"):
        parse(b"X = " + b"{" * 10_000 + b"}" * 10_000)


# --- properties --------------------------------------------------------------------------------


def to_lua(value: LuaValue) -> str:
    """Write a value as the client would, for the round trip."""
    match value:
        case None:
            return "nil"
        case bool():
            return "true" if value else "false"
        case int():
            return str(value)
        case float():
            return repr(value)
        case str():
            out: list[str] = []
            for char in value:
                if char in '"\\':
                    out.append("\\" + char)
                elif ord(char) < 32 or ord(char) == 127:
                    out.append(f"\\{ord(char):03d}")
                else:
                    out.append(char)
            return '"' + "".join(out) + '"'
        case list():
            return "{\n" + "".join(f"\t{to_lua(v)},\n" for v in value) + "}"
        case dict():
            return (
                "{\n" + "".join(f"\t[{to_lua(k)}] = {to_lua(v)},\n" for k, v in value.items()) + "}"
            )


scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False).filter(lambda f: not f.is_integer())
    | st.text(alphabet=st.characters(exclude_categories=("Cs",)), max_size=40)
)
# Lists are never empty and dict keys are never 1..n, so each shape comes back as it went.
values = st.recursive(
    scalars,
    lambda inner: (
        st.lists(inner, min_size=1, max_size=5)
        | st.dictionaries(st.text(max_size=12), inner, min_size=1, max_size=5)
    ),
    max_leaves=25,
)


@settings(max_examples=300, deadline=None)
@given(values)
def test_what_the_client_writes_reads_back_the_same(value: LuaValue) -> None:
    text = to_lua(value)
    if len(text.encode()) > 1024 * 1024:
        return
    back = parse(f"X = {text}".encode())["X"]
    assert back == value or (isinstance(value, float) and math.isclose(back, value))  # type: ignore[arg-type]


@settings(max_examples=500, deadline=None)
@given(st.binary(max_size=2048))
def test_random_bytes_fail_only_with_the_readers_own_error(data: bytes) -> None:
    with contextlib.suppress(SavedVariablesError):
        parse(data)


lua_ish = st.text(
    alphabet=st.sampled_from(list("X={}[]\"',;=-.0123456789eExabtrufnl \n\t\\-[=]")),
    max_size=300,
)


@settings(max_examples=500, deadline=None)
@given(lua_ish)
def test_lua_like_noise_fails_only_with_the_readers_own_error(text: str) -> None:
    with contextlib.suppress(SavedVariablesError):
        parse(text.encode())
