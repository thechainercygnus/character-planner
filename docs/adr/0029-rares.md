# 0029: Rares as a pool source, merged by id against a cache that ignores filters

Status: accepted (2026-11-13)

## Context

Rares drop gear in the leveling range, and the item pool (ADR 0006) knew only dungeon
drops and dungeon quest rewards (#6). Forever Companion's `GET /rares` lists every rare
with its zone, `levels`, `faction`, spawn `coords`, `elite` flag and `loot` (the same
`Loot` shape as a dungeon's drop table). It's unpaged.

Checked on 2026-11-13:

- The list's CDN cache is keyed on the path alone, as `/items` is (ADR 0004). One
  unfiltered request got another client's `?zone=The Barrens` result, 3 rares; the next,
  a minute later, 28. Every query string then returned the same 28.
- The 28 span 12 zones, both factions and levels 3 to 60, so they look like the whole
  list. Only 5 have loot listed: 4 uncommon and 1 rare item, all for both factions, in
  levels 10 to 30.
- `levels` comes as `"10–25"` (an en dash) or `"60"`, not the spec's `"24-25"`.

## Decision

- `rares.py` fetches the list once per pool refresh and stores each rare's raw object in
  `CompanionRare`, keyed by id (migration 0005). Every fetch is merged in by id and never
  replaces the stored set: a filtered response is a subset of the full list, so it can't
  remove anything, and the stored set only grows toward the full list.
- `build_pool` adds each drop of a rare the character's faction can reach, as a
  `PoolSource` of kind `rare` with the rare's id, name, zone, level range, spawn count and
  elite flag. A rare source has no dungeon; `place` names it either way.
- The rare's level range drives the level window and, for an item with no required
  level, its `effective_level`, as a dungeon's does.
- `levels` is read as the lowest and highest number in the string, whatever separates
  them.
- Rares are left out of "Dungeons worth running": you can't queue for a rare. Their drops
  appear on the Upgrades tab as "Rare: Humar the Pridelord, The Barrens (10–25), 1 spawn".

## Consequences

- A rare Forever Companion removes stays stored. That's harmless while rares are only
  ever added; a forced cleanup can come if one is ever renamed or retired.
- With 5 drops listed today, rares rarely change a recommendation yet. The source is in
  place for when Forever Companion lists more loot.
