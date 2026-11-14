"""The API reference for the docs site, generated from the app's own OpenAPI schema.

Run with: uv run character-planner-api-docs

Writes docs/api.md (a readable page) and docs/_static/openapi.json (the schema itself).
A running instance serves the same thing interactively at /docs. A test fails when the
committed files no longer match the code, so they can't drift (OpenSSF
documentation_interface, #86).
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from character_planner import fields
from character_planner.app import create_app
from character_planner.config import Settings

DOCS = Path("docs")
PAGE = DOCS / "api.md"
SCHEMA = DOCS / "_static" / "openapi.json"
REF = "#/components/schemas/"

INTRO = """\
# API reference

The planner's HTTP API, generated from its OpenAPI schema by
`uv run character-planner-api-docs`; don't edit this page by hand. A running instance
serves the same reference interactively at `/docs`, and the raw schema is
[openapi.json](_static/openapi.json).

- Data routes are under `/api`; the optional Battle.net login is under `/auth`.
- Requests that change something (`POST`, `PUT`, `PATCH`, `DELETE`) need the header
  `X-Requested-With: character-planner`, as the web app sends it; reads don't.
- The API answers only to the host names it's configured for (`PLANNER_HOSTS`).
- Errors come back as JSON with a `detail` field; invalid input gets 422.
"""


def app_schema() -> dict[str, Any]:
    """The OpenAPI schema of an app built with default settings, ignoring any .env."""
    settings = Settings(_env_file=None, database_url="sqlite://")  # pyright: ignore[reportCallIssue]
    return create_app(settings).openapi()


def type_of(schema: Any) -> str:
    """A schema as a short type: `string`, `integer (1-10)`, `LookAhead`, `list[Item]`."""
    node = fields.as_mapping(schema)
    ref = node.get("$ref")
    if isinstance(ref, str):
        return f"[{ref.removeprefix(REF)}](#{anchor(ref.removeprefix(REF))})"
    options = fields.as_list(node.get("anyOf"))
    if options:
        kinds = [type_of(o) for o in options]
        nullable = "null" in kinds
        named = " or ".join(k for k in kinds if k != "null")
        return f"{named} or null" if nullable else named
    if "enum" in node:
        return " \\| ".join(f"`{v}`" for v in fields.as_list(node.get("enum")))
    kind = node.get("type")
    if kind == "array":
        return f"list of {type_of(node.get('items'))}"
    if kind == "object" and "additionalProperties" in node:
        extra = node.get("additionalProperties")
        return f"map of {type_of(extra)}" if isinstance(extra, Mapping) else "object"
    text = str(kind) if isinstance(kind, str) else "any"
    limits = [
        f"{key} {node[key]}"
        for key in ("minimum", "exclusiveMinimum", "maximum", "minLength", "maxLength", "pattern")
        if key in node
    ]
    return f"{text} ({', '.join(limits)})" if limits else text


def anchor(name: str) -> str:
    return "schema-" + name.lower()


def cell(text: Any) -> str:
    """A value fit for a Markdown table cell: one line, pipes escaped."""
    return " ".join(str(text).split()).replace("|", "\\|") if text is not None else ""


def operation(method: str, path: str, op: Mapping[str, Any]) -> list[str]:
    lines = [f"### `{method.upper()} {path}`", ""]
    description = op.get("description") or op.get("summary")
    if isinstance(description, str):
        lines += [" ".join(description.split()), ""]
    params = [fields.as_mapping(p) for p in fields.as_list(op.get("parameters"))]
    if params:
        lines += [
            "| Parameter | In | Type | Required | Default |",
            "| --- | --- | --- | --- | --- |",
        ]
        for p in params:
            schema = fields.as_mapping(p.get("schema"))
            default = schema.get("default")
            lines.append(
                f"| `{p.get('name')}` | {p.get('in')} | {cell(type_of(schema))} | "
                f"{'yes' if p.get('required') else 'no'} | "
                f"{cell(json.dumps(default)) if 'default' in schema else ''} |"
            )
        lines.append("")
    body = fields.get(op, "requestBody", "content", "application/json", "schema")
    if body is not None:
        lines += [f"**Body:** {type_of(body)}", ""]
    for status, response in sorted(fields.as_mapping(op.get("responses")).items()):
        if status == "422":
            continue  # every route with input can answer 422; said once in the intro
        result = fields.get(response, "content", "application/json", "schema")
        shown = type_of(result) if result else "no body"
        lines += [f"**{status}:** {shown}", ""]
    return lines


def schema_section(name: str, schema: Mapping[str, Any]) -> list[str]:
    # A MyST label: [Name](#schema-name) links resolve to it on the docs site.
    lines = [f"({anchor(name)})=", f"### {name}", ""]
    description = schema.get("description")
    if isinstance(description, str):
        lines += [" ".join(description.split()), ""]
    properties = fields.as_mapping(schema.get("properties"))
    if not properties:
        lines += [f"Type: {type_of(schema)}", ""]
        return lines
    required = set(fields.as_list(schema.get("required")))
    lines += ["| Field | Type | Required |", "| --- | --- | --- |"]
    for field, spec in properties.items():
        lines.append(
            f"| `{field}` | {cell(type_of(spec))} | {'yes' if field in required else 'no'} |"
        )
    return [*lines, ""]


def markdown(schema: Mapping[str, Any]) -> str:
    """The reference page: operations grouped by area, then every schema."""
    groups: dict[str, list[str]] = {}
    for path, item in sorted(fields.as_mapping(schema.get("paths")).items()):
        area = path.split("/")[2] if path.startswith("/api/") else path.split("/")[1]
        for method, op in fields.as_mapping(item).items():
            groups.setdefault(area, []).extend(operation(method, path, fields.as_mapping(op)))
    lines = [INTRO, "## Endpoints", ""]
    for area, ops in groups.items():
        lines += [f"## `{area}`", "", *ops]
    lines += ["## Schemas", ""]
    schemas = fields.as_mapping(fields.get(schema, "components", "schemas"))
    for name, spec in sorted(schemas.items()):
        lines += schema_section(name, fields.as_mapping(spec))
    return "\n".join(lines).rstrip() + "\n"


def rendered() -> tuple[str, str]:
    """(page, schema JSON) as they should be committed."""
    schema = app_schema()
    return markdown(schema), json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    page, schema = rendered()
    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    SCHEMA.write_text(schema, encoding="utf-8", newline="\n")
    print(f"Wrote {PAGE} and {SCHEMA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
