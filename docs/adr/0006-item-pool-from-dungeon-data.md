# 0006: Build the item pool from Forever Companion's dungeon data

Status: accepted (2026-11-11)

## Context

Phase C of the recommendation engine proposes gear targets per slot instead of only
scoring the ones listed in `gear_targets.yaml`. That needs a pool of candidate items.
Forever Companion's `GET /items` list would be the natural source, but its CDN cache is
keyed on the path alone, so its filters and paging are ignored (ADR 0004; reported to
them on 2026-11-11, no fix yet). Blizzard's item search lacks most dungeon loot.

The vendored spec (`docs/vendor/`) offers another route:

- `GET /dungeons` lists every dungeon and has no paging, so the cache doesn't matter.
- `GET /dungeons/{id}` puts the id in the path (cache-safe) and returns the full drop
  table (item id, slot, quality, boss) and the dungeon's quests with reward item ids.

Checked by hand on 2026-11-11: 35 dungeons listed; the Hall of Thanes drop table has
item ids for every drop, including Golemguard Chest (271098) and Spiritwraith Drape
(271097), which the id scans never found.

## Decision

- `dungeons.py` fetches the list and each dungeon's detail, skipping `announced`
  dungeons, and stores the raw detail payloads in `CompanionDungeon` (ADR 0002), cached
  for 24 hours.
- `pool.py` builds the pool from the stored dungeons: every drop, plus every quest reward
  the character's faction can take, each with its sources (dungeon, boss or quest,
  dungeon level range).
- Item details come from `GET /items/{id}` as before, but only for pool items whose source
  dungeons overlap a level window (level - 3 to level + 10), cached for 7 days. Requests are
  paced 0.55 s apart (`companion_request_pause`) to stay under 120 requests/min.
- Gear targets that name an item without an `item_id` get one from the pool when exactly
  one pool item has that name. Ids in the YAML always win.
- `POST /api/pool/refresh` and `uv run character-planner-pool` (with progress) do the
  refresh; `GET /api/pool` returns the pool for the level window.

## Consequences

- The first refresh is a few hundred requests (a few minutes); later ones fetch only
  what's stale.
- The pool covers dungeon drops and dungeon quest rewards only. Zone quest rewards (the
  quest list is paged, so cache-broken), vendor and crafted gear stay in
  `gear_targets.yaml`.
- The pool depends on a fan site; if it disappears, the stored payloads keep working
  and the YAML still drives the plan.
- Forever Companion slot names (`wrist`, `main-hand`, `staff`) differ from Battle.net
  slot types (`WRIST`, `MAIN_HAND`); phase C maps them.
