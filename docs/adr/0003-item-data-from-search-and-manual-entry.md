# 0003: Item data from Battle.net search, filled in by hand

Status: accepted (2026-11-11)

## Context

To judge a gear target we need its item level, armor type and ideally stats. The item
probe (`uv run character-planner-probe-items`, 2026-11-11) found:

- `/data/wow/item/{id}` returns 404 in `static-forever-us` and the versioned namespace.
  Blizzard obfuscates Forever item stats on purpose.
- `/data/wow/search/item` works. It matches words, not names, and returns item level,
  quality, armor subclass, slot and required level, but no armor value or stats.
- Forever-new items (Hall of Thanes drops) are missing from the search index.
- `/data/wow/media/item/{id}` works and gives icon URLs.
- Third-party databases (ForeverDB, Wowhead, RankedBoost) have stats from the game files
  but publish no API; scraping them is fragile and likely against their terms.

## Decision

- Look up each gear target by name with an app-only (client credentials) token, keep only
  the exact-name match, and cache it in `CatalogItem`, including "not found".
- Search matches any word, so names with common words ("Cape of the Brotherhood") bury the
  item pages deep. If the full name finds nothing, retry with each distinctive word,
  longest first, still keeping only the exact-name match.
- Fetch icons for catalog and equipped items into `ItemIcon`.
- Judge targets on item level: more than 2 above equipped is an upgrade, more than 2
  below is a downgrade, otherwise a sidegrade. Flag lighter armor (Leather replacing Mail).
- `gear_targets.yaml` accepts hand-entered `item_id`, `item_level`, `armor_type`, `armor`
  and `stats`, used where the API has nothing. Rows show whether data is `api` or `manual`.
- The catalog refreshes after each sync for uncached names; `POST /api/items/refresh?force=true`
  retries everything.

## Consequences

- No exact stat deltas until Blizzard serves item details. Re-run the probe after patches;
  if the item endpoint starts answering, add a lookup by id.
- Forever-new targets need manual data to get a verdict; without it they show `unknown`.
- Item lookups never block a character sync.
