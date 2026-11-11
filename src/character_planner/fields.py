"""Defensive readers for undocumented API JSON: a missing or reshaped field is None."""

from collections.abc import Mapping
from typing import Any


def get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def name(value: Any) -> str | None:
    """Localised names arrive as a string, or as {"en_US": ...} without a locale param."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return value.get("en_US") or next(iter(value.values()), None)
    return None


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
