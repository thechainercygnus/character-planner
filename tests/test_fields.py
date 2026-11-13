"""The defensive JSON readers every parser uses (fields.py, #85)."""

from typing import Any

import pytest

from character_planner import fields


@pytest.mark.parametrize(
    ("value", "expected"),
    [([1, "a"], [1, "a"]), ([], []), ({"a": 1}, []), ("text", []), (None, []), (3, [])],
)
def test_as_list_keeps_arrays_and_drops_the_rest(value: Any, expected: list[Any]) -> None:
    assert fields.as_list(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [({"a": 1}, {"a": 1}), ({}, {}), ([("a", 1)], {}), ("text", {}), (None, {})],
)
def test_as_mapping_keeps_objects_and_drops_the_rest(value: Any, expected: dict[str, Any]) -> None:
    assert fields.as_mapping(value) == expected


def test_get_walks_nested_objects_and_stops_at_anything_else() -> None:
    data = {"item": {"quality": {"type": "RARE"}}, "list": [1]}
    assert fields.get(data, "item", "quality", "type") == "RARE"
    assert fields.get(data, "item", "missing") is None
    assert fields.get(data, "list", "0") is None  # arrays aren't walked by key
    assert fields.get(None, "x") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Gnome", "Gnome"),
        ({"en_US": "Gnome", "fr_FR": "Gnome FR"}, "Gnome"),  # localised, without locale=
        ({"de_DE": "Gnom"}, "Gnom"),  # no English: the first one
        ({"en_US": 7}, None),  # not a string: no name
        ({}, None),
        (None, None),
    ],
)
def test_name_reads_plain_and_localised_names(value: Any, expected: str | None) -> None:
    assert fields.name(value) == expected


def test_numbers_reject_booleans() -> None:
    assert (fields.as_int(3), fields.as_int(True), fields.as_int(3.5)) == (3, None, None)
    assert (fields.as_float(3), fields.as_float(2.5), fields.as_float(False)) == (3.0, 2.5, None)
