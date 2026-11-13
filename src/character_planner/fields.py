"""Defensive readers for undocumented API JSON: a missing or reshaped field is None.

JSON comes in as Any. Narrowing Any with isinstance gives containers of unknown types,
so these helpers hand back typed views instead: `as_list` and `as_mapping` for
containers, `get`, `name`, `as_int` and `as_float` for values (#85).
"""

from collections.abc import Mapping
from typing import Any, cast


def as_mapping(value: Any) -> Mapping[str, Any]:
    """A JSON object, or an empty one when the value isn't an object."""
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    """A JSON array, or an empty one when the value isn't an array."""
    return cast(list[Any], value) if isinstance(value, list) else []


def get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, Mapping):
            return None
        data = as_mapping(data).get(key)
    return data


def name(value: Any) -> str | None:
    """Localised names arrive as a string, or as {"en_US": ...} without a locale param."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        names = as_mapping(value)
        found = names.get("en_US") or next(iter(names.values()), None)
        return found if isinstance(found, str) else None
    return None


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
