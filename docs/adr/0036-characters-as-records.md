# 0036: Characters are records; data belongs to one

Status: accepted (2026-11-14)

## Context

Everything assumed one character (#14). Which character it was came from `.env`
(`CHARACTER_NAME`, `CHARACTER_SURNAME`, `BNET_REGION`), and snapshots, progress history and
settings had no owner. Multiple characters (#14, #15) and then users (#16, #17) need a
character to hang data on.

## Decision

1. **A `character` table.**
   - It holds the region, the slug Forever's routes use (`name-surname`, lowercase), the
     name and surname, and Blizzard's character id, class, race and faction.
   - The last four are copied from the newest profile at each sync. The raw snapshots stay
     the source of truth (ADR 0002).
   - A region and slug pair is unique.
2. **Data belongs to a character.**
   - `snapshot` and `progresshistory` carry `character_id`.
   - Every query that reads them takes a character, so no view can mix two characters.
   - So do the settings edited in the app: Upgrades rules, weight presets and the active
     one, gear targets, talent plan, dismissed items, class quests marked done and alert
     state. Each settings table has an id key and a `character_id`, unique per character;
     "none" still means the class's shipped default.
   - Two things stay instance-wide. Enchant corrections fix shared reference data, not a
     character's choices (ADR 0033). Alert destinations belong to whoever runs the
     instance until users exist (#16).
3. **`.env` seeds the first character, once.**
   - When the table is empty, the first use creates a character from `CHARACTER_NAME`,
     `CHARACTER_SURNAME` and `BNET_REGION`.
   - Rows stored before characters existed (no `character_id`) are adopted by it.
   - After that, those settings aren't read. Which characters are tracked is data, changed
     in the app (#14's last step, #15).
   - Seeding happens in code, not in the migration: the migration can't read settings, and
     every entry point (API, worker, CLI) goes through the same step.
4. **A request names its character with the `X-Character-Id` header.**
   - Without the header, a request gets the first character, by id. Plain links, the
     summary and older clients keep working.
   - #14 offered `/api/characters/{id}/...` routes or a header. The header keeps one
     set of routes, so there's no alias to keep and nothing to retire. The web app
     already sends a header on every request (#124).
   - An unknown id answers 404.
   - The header's switcher lists the characters (`GET /api/characters`) and adds one by
     name, surname and region (`POST /api/characters`).
5. **Every character is synced.** The worker syncs each tracked character in turn. Shared
   refreshes (the item pool's level window, talent trees, first data load) follow the
   first character.
6. **Deleting is per character.** `DELETE /api/character` stops tracking the selected
   character and deletes its rows. `character-planner-db erase` still deletes everything.

## Consequences

- An existing database upgrades in place. Migrations 0010 and 0011 add the table and
  columns and copy settings without an owner; the first start assigns every such row to
  the seeded character, and each start adopts any left over. A downgrade keeps the first
  character's settings.
- Changing `CHARACTER_NAME` after the first start no longer changes the tracked character.
  The self-hosting and privacy docs say so.
- Sync, retention, alerts and every view take a character. Shared game-data caches stay
  global.
- Forgetting a character Blizzard no longer has deletes only that character's data.
