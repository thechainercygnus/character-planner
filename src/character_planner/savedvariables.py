"""A reader for WoW SavedVariables files (#183, ADR 0047).

The client writes an addon's saved variables as Lua source: assignments of tables,
strings, numbers and booleans. This reads that subset and nothing more. It never executes
anything: there's no Lua interpreter, and anything outside the subset (a function call, an
operator, a name used as a value) is an error naming its line and column. Uploaded files
are untrusted, so every size has a hard limit.

The subset, as `addon/SCHEMA.md` lists it:
- top-level assignments, `Name = value`;
- tables: `{}` with `["key"] = value`, `[1] = value`, `key = value` and plain list entries,
  separated by `,` or `;`, with an optional trailing separator;
- strings in `"` or `'`, with Lua's escapes;
- numbers: decimal (with a fraction or exponent) and hexadecimal integers, optionally
  negative; not `inf` or `nan`;
- `true`, `false` and `nil`;
- `--` and `--[[ ]]` comments, a UTF-8 byte-order mark, CRLF line endings.

A table whose keys are exactly 1..n becomes a list; any other table a dict. An empty
table is an empty dict: the schema layer reads it as an empty list where it wants one.
"""

import math
from dataclasses import dataclass
from typing import Final

type LuaKey = str | int | float | bool
type LuaValue = bool | int | float | str | list["LuaValue"] | dict[LuaKey, "LuaValue"] | None


@dataclass(frozen=True)
class Limits:
    """ADR 0047's limits. A full character's export comes to roughly 100 KiB."""

    max_bytes: int = 1024 * 1024
    max_depth: int = 16
    max_values: int = 50_000
    max_string: int = 4096  # bytes, after escapes
    max_number: int = 64  # characters in one number literal


LIMITS: Final = Limits()


class SavedVariablesError(ValueError):
    """The file isn't a SavedVariables file this reader accepts. The message says where
    and why, and never quotes more of the file than a token."""


_ESCAPES: Final = {
    "a": 7,
    "b": 8,
    "f": 12,
    "n": 10,
    "r": 13,
    "t": 9,
    "v": 11,
    "\\": 92,
    '"': 34,
    "'": 39,
    "\n": 10,
}
_SPACE: Final = frozenset(" \t\r\n\f\v")
_NAME_START: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_NAME: Final = _NAME_START | frozenset("0123456789")
_DIGITS: Final = frozenset("0123456789")
_HEX: Final = frozenset("0123456789abcdefABCDEF")
_KEYWORDS: Final = {"true": True, "false": False, "nil": None}


class _Reader:
    def __init__(self, text: str, limits: Limits) -> None:
        self.text: str = text
        self.pos: int = 0
        self.limits: Limits = limits
        self.values: int = 0

    # --- errors -------------------------------------------------------------------------

    def fail(self, message: str, at: int | None = None) -> SavedVariablesError:
        at = self.pos if at is None else at
        line = self.text.count("\n", 0, at) + 1
        column = at - (self.text.rfind("\n", 0, at) + 1) + 1
        return SavedVariablesError(f"line {line}, column {column}: {message}")

    def token(self) -> str:
        """The text at the error, for the message: short, so a file never echoes back."""
        if self.pos >= len(self.text):
            return "the end of the file"
        start = self.pos
        end = start + 1
        while end < len(self.text) and end - start < 20 and self.text[end] in _NAME:
            end += 1
        return repr(self.text[start:end])

    # --- whitespace and comments ----------------------------------------------------------

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char in _SPACE:
                self.pos += 1
            elif text.startswith("--", self.pos):
                self.pos += 2
                level = self.long_bracket()
                if level is not None:
                    close = "]" + "=" * level + "]"
                    end = text.find(close, self.pos)
                    if end < 0:
                        raise self.fail("a long comment is never closed")
                    self.pos = end + len(close)
                else:
                    end = text.find("\n", self.pos)
                    self.pos = len(text) if end < 0 else end + 1
            else:
                return

    def long_bracket(self) -> int | None:
        """At `[[` or `[==[`: step past it and return its level; otherwise None."""
        text = self.text
        if not text.startswith("[", self.pos):
            return None
        end = self.pos + 1
        while end < len(text) and text[end] == "=":
            end += 1
        if end < len(text) and text[end] == "[":
            level = end - self.pos - 1
            self.pos = end + 1
            return level
        return None

    def expect(self, char: str) -> None:
        self.skip()
        if not self.text.startswith(char, self.pos):
            raise self.fail(f"expected {char!r}, found {self.token()}")
        self.pos += 1

    # --- the grammar --------------------------------------------------------------------

    def document(self) -> dict[str, LuaValue]:
        result: dict[str, LuaValue] = {}
        self.skip()
        while self.pos < len(self.text):
            name = self.name()
            if name is None or name in _KEYWORDS:
                raise self.fail(f"expected a variable name, found {self.token()}")
            self.expect("=")
            result[name] = self.value(depth=0)
            self.skip()
            # Statements may be separated by a semicolon.
            if self.text.startswith(";", self.pos):
                self.pos += 1
                self.skip()
        return result

    def name(self) -> str | None:
        text = self.text
        if self.pos >= len(text) or text[self.pos] not in _NAME_START:
            return None
        end = self.pos + 1
        while end < len(text) and text[end] in _NAME:
            end += 1
        name = text[self.pos : end]
        self.pos = end
        return name

    def count(self) -> None:
        self.values += 1
        if self.values > self.limits.max_values:
            raise self.fail(f"more than {self.limits.max_values} values")

    def value(self, depth: int) -> LuaValue:
        self.skip()
        self.count()
        if self.pos >= len(self.text):
            raise self.fail("expected a value, found the end of the file")
        char = self.text[self.pos]
        if char == "{":
            return self.table(depth + 1)
        if char in "\"'":
            return self.string()
        if char in _DIGITS or char in "-.":
            return self.number()
        start = self.pos
        name = self.name()
        if name in _KEYWORDS:
            return _KEYWORDS[name]
        self.pos = start
        # A name, a call, an operator, a long string: all outside the subset.
        raise self.fail(f"expected a value, found {self.token()}")

    def table(self, depth: int) -> LuaValue:
        if depth > self.limits.max_depth:
            raise self.fail(f"tables nested more than {self.limits.max_depth} deep")
        self.pos += 1  # the "{"
        entries: dict[LuaKey, LuaValue] = {}
        position = 1
        while True:
            self.skip()
            if self.text.startswith("}", self.pos):
                self.pos += 1
                break
            start = self.pos
            if self.text.startswith("[", self.pos) and self.long_bracket() is None:
                self.pos += 1
                key = self.value(depth)
                self.expect("]")
                self.expect("=")
                entries[self.key(key, start)] = self.value(depth)
            elif (name := self.name()) is not None and name not in _KEYWORDS:
                self.expect("=")
                entries[name] = self.value(depth)
            else:
                self.pos = start
                entries[position] = self.value(depth)
                position += 1
            self.skip()
            if self.pos < len(self.text) and self.text[self.pos] in ",;":
                self.pos += 1
            elif not self.text.startswith("}", self.pos):
                raise self.fail(f"expected ',' or '}}', found {self.token()}")
        # Exactly 1..n: a list, in order.
        if entries and all(isinstance(k, int) and not isinstance(k, bool) for k in entries):
            keys = sorted(k for k in entries if isinstance(k, int))
            if keys == list(range(1, len(keys) + 1)):
                return [entries[k] for k in keys]
        return entries

    def key(self, key: LuaValue, at: int) -> LuaKey:
        if key is None or isinstance(key, list | dict):
            raise self.fail("a table key must be a string, number or boolean", at)
        # Lua treats 1.0 and 1 as the same key.
        if isinstance(key, float) and key.is_integer():
            return int(key)
        return key

    def string(self) -> str:
        text = self.text
        quote = text[self.pos]
        start = self.pos
        self.pos += 1
        out = bytearray()
        while True:
            if self.pos >= len(text):
                raise self.fail("a string is never closed", start)
            char = text[self.pos]
            if char == quote:
                self.pos += 1
                break
            if char == "\n":
                raise self.fail("a line break inside a string", self.pos)
            if char == "\\":
                self.escape(out)
            else:
                out += char.encode("utf-8")
                self.pos += 1
            if len(out) > self.limits.max_string:
                raise self.fail(f"a string longer than {self.limits.max_string} bytes", start)
        # Lua strings are bytes; the client writes UTF-8. Anything else shows as U+FFFD.
        return out.decode("utf-8", errors="replace")

    def escape(self, out: bytearray) -> None:
        text = self.text
        at = self.pos
        self.pos += 1  # the backslash
        if self.pos >= len(text):
            raise self.fail("a string is never closed", at)
        char = text[self.pos]
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
            self.pos += 1
        elif char == "\r":  # an escaped CRLF line break
            out.append(10)
            self.pos += 2 if text.startswith("\r\n", self.pos) else 1
        elif char == "z":  # skip the whitespace that follows
            self.pos += 1
            while self.pos < len(text) and text[self.pos] in _SPACE:
                self.pos += 1
        elif char == "x":
            digits = text[self.pos + 1 : self.pos + 3]
            if len(digits) != 2 or not set(digits) <= _HEX:
                raise self.fail("\\x needs two hexadecimal digits", at)
            out.append(int(digits, 16))
            self.pos += 3
        elif char in _DIGITS:
            end = self.pos
            while end < len(text) and end - self.pos < 3 and text[end] in _DIGITS:
                end += 1
            code = int(text[self.pos : end])
            if code > 255:
                raise self.fail("a decimal escape above 255", at)
            out.append(code)
            self.pos = end
        elif char == "u" and text.startswith("{", self.pos + 1):
            end = text.find("}", self.pos + 2)
            digits = text[self.pos + 2 : end] if end > 0 else ""
            if not digits or len(digits) > 8 or not set(digits) <= _HEX:
                raise self.fail("\\u{...} needs hexadecimal digits", at)
            code = int(digits, 16)
            if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                raise self.fail("\\u{...} isn't a character", at)
            out += chr(code).encode("utf-8")
            self.pos = end + 1
        else:
            raise self.fail(f"an unknown escape \\{char}", at)

    def number(self) -> int | float:
        text = self.text
        start = self.pos
        end = start + 1 if text[start] == "-" else start
        if text.startswith(("0x", "0X"), end):
            end += 2
            digits_start = end
            while end < len(text) and text[end] in _HEX:
                end += 1
            if end == digits_start:
                raise self.fail("a hexadecimal number needs digits", start)
        else:
            while end < len(text) and (text[end] in _DIGITS or text[end] in ".eE"):
                if text[end] in "eE" and end + 1 < len(text) and text[end + 1] in "+-":
                    end += 1
                end += 1
        literal = text[start:end]
        if len(literal) > self.limits.max_number:
            raise self.fail(f"a number longer than {self.limits.max_number} characters", start)
        # Glued to a name ("12abc", "-inf"): not a number.
        if end < len(text) and text[end] in _NAME:
            self.pos = start
            raise self.fail(f"expected a number, found {self.token()}")
        self.pos = end
        try:
            if literal.lstrip("-")[:2].lower() == "0x":
                return int(literal, 16)
            number = float(literal) if any(c in literal for c in ".eE") else int(literal)
        except ValueError:
            raise self.fail(f"{literal!r} isn't a number", start) from None
        # Outside the try: this error is a ValueError too, and mustn't be caught there.
        if isinstance(number, float) and not math.isfinite(number):
            raise self.fail(f"{literal!r} is out of range", start)  # 1e400 overflows to inf
        return number


def parse(data: bytes, limits: Limits = LIMITS) -> dict[str, LuaValue]:
    """The file's top-level assignments, name -> value. Raises SavedVariablesError for
    anything this reader doesn't accept, over a limit included."""
    if len(data) > limits.max_bytes:
        raise SavedVariablesError(f"the file is larger than {limits.max_bytes} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SavedVariablesError(f"not UTF-8 text (byte {error.start})") from None
    text = text.removeprefix("﻿")
    if "\x00" in text:
        raise SavedVariablesError("not a text file: it contains a NUL byte")
    return _Reader(text, limits).document()
