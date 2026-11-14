"""The API reference on the docs site (api_reference.py, #86's documentation_interface)."""

from typing import Any

import pytest

from character_planner.api_reference import PAGE, SCHEMA, markdown, rendered, type_of

from .conftest import REPO_ROOT


def test_the_committed_reference_matches_the_code() -> None:
    """Regenerate with `uv run character-planner-api-docs` when this fails: an endpoint or
    a model changed, and docs/api.md and docs/_static/openapi.json must follow."""
    page, schema = rendered()
    assert (REPO_ROOT / SCHEMA).read_text(encoding="utf-8") == schema
    assert (REPO_ROOT / PAGE).read_text(encoding="utf-8") == page


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "string"}, "string"),
        ({"type": "integer", "minimum": 1, "maximum": 10}, "integer (minimum 1, maximum 10)"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string or null"),
        ({"$ref": "#/components/schemas/LookAhead"}, "[LookAhead](#schema-lookahead)"),
        ({"type": "array", "items": {"type": "integer"}}, "list of integer"),
        ({"type": "object", "additionalProperties": {"type": "number"}}, "map of number"),
        ({"type": "string", "enum": ["drop", "quest"]}, r"`drop` \| `quest`"),
        ({}, "any"),
    ],
)
def test_types_read_plainly(schema: dict[str, Any], expected: str) -> None:
    assert type_of(schema) == expected


def test_the_page_lists_endpoints_and_schemas() -> None:
    page = markdown(
        {
            "paths": {
                "/api/things/{id}": {
                    "put": {
                        "description": "Change a thing.",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer"},
                            }
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Thing"}
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}, "422": {"description": "Bad"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Thing": {"properties": {"name": {"type": "string"}}, "required": ["name"]}
                }
            },
        }
    )
    assert "### `PUT /api/things/{id}`" in page
    assert "| `id` | path | integer | yes |  |" in page
    assert "**Body:** [Thing](#schema-thing)" in page
    assert "**200:** no body" in page and "**422:**" not in page
    assert "(schema-thing)=\n### Thing" in page
    assert "| `name` | string | yes |" in page
