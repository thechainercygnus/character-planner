# 0004: Forever Companion as a second item source, by item id only

Status: accepted (2026-11-11)

## Context

ADR 0003 left most gear targets without data: Blizzard hides Forever dungeon loot from
item search and serves no item stats. Forever Companion (https://forevercompanion.io) is a
free, keyless fan API (120 requests/min per IP) with item level, armor, stat lines,
drop sources and quest rewards. Its OpenAPI spec is vendored at
`docs/vendor/forevercompanion-openapi.json`.

Probing on 2026-11-11 found:

- `GET /items/{id}` works: full tooltip (armor, stats), `dropsFrom`, `rewardFrom`.
- `GET /items` (list with `q`, `ids`, `limit`, `offset`) is served from a Netlify cache
  keyed on the path only (`Cache-Status: "Netlify Durable"; hit`): every request gets
  whatever list was cached last, and `page` describes someone else's query. Reported
  to the maintainers.
- `meta.updatedAt` was four days old despite a documented ~6 hour sync.

## Decision

- Key items by id. `gear_targets.yaml` carries `item_id`; Blizzard search supplies ids
  where it finds the item. Ids are found with
  `uv run character-planner-probe-companion --ids <id or range>` or a Wowhead URL.
- Use only `GET /items/{id}`. Cache responses in `CompanionItem`; refetch after 24 hours
  or on a forced refresh; stop a batch at the first 429.
- Merge per field: manual > Blizzard > Forever Companion. Record which sources fed each
  target and list disagreements (item level, armor type) instead of hiding them.
- Read armor and stats from tooltip lines (`"100 Armor"`, `"+7 Stamina"`) and compute
  armor and stat changes against the equipped item.
- Show Forever Companion's required credit wherever its data appears (UI and summary).
- A failing source never fails a sync or a refresh; errors are reported per source.

## Consequences

- Real stat changes (`+27 armor, +7 Stamina`) for targets Companion knows.
- New targets need an `item_id` to use Companion until its list endpoint is fixed; when it
  is, add name-to-id discovery from the list, validating `page` against the request.
- Data is fan-collected and can be stale or wrong; the `verified` count and conflict list
  make that visible. Swap in the open dataset (wowlayerup-forever/opendata) as another
  adapter if it ships.
