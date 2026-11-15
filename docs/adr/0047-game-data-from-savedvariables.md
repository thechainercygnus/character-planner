# 0047: Game data from a SavedVariables addon: schema, upload, a purpose-built parser

Status: accepted (2026-11-15)

## Context

The Battle.net API shows equipped gear but not bags, bank or quest progress, and it
updates some time after you play (#177). A small in-game addon can record those; this
decides how its data reaches the planner. Facts checked on Bryce's install (2026-11-15):
- Forever addons declare `## Interface: 16001`.
- SavedVariables live under `_forever_\WTF\Account\<ACCOUNT>\`, per character in
  `91\<Character>\SavedVariables\`. The realm folder is a number: Forever's API has no
  realms.
- The client writes them only on logout, `/reload` or exit, so a file is a snapshot.

## Decision

Bryce chose upload first and a purpose-built parser (2026-11-15). The rest follows.

1. **The schema is versioned, and documented in `addon/SCHEMA.md`.**
   - One table, `CharacterPlannerExportDB`, with `schemaVersion = 1`.
   - It holds the character's identifiers, then `bags`, `bank` and `quests`, each with
     its own `capturedAt` (Unix seconds, UTC).
   - Items carry ids, counts and quality only. Names, icons and stats come from the
     planner's catalog, as they do for Battle.net gear.
   - The bank section is absent until the bank has been opened, so "not seen yet" and
     "empty" differ.
   - The parser refuses versions it doesn't know. A change it would misread needs a new
     version, which the parser learns before the addon ships it.
2. **Stored per character.**
   - The `.toc` declares `## SavedVariablesPerCharacter:`. One file is one character,
     which matches the planner's characters as records (ADR 0036).
   - Nothing is account-wide.
3. **Upload first; a local folder later (#187).**
   - The planner runs in the homelab, and with users on, each person's files are on
     their own machine. The backend can't read them, so the app takes an upload.
   - Reading `WTF_PATH` directly comes later, for an instance on the gaming PC. It uses
     the same parser.
   - Imports are on demand: no file watcher.
4. **An upload goes to the selected character.**
   - The upload is for the character the request names (`X-Character-Id`), like every
     other route, so with users on it can only be the user's own.
   - The file must agree with it: the name must match, ignoring case. So must the surname
     and region, where the file has them.
   - A mismatch is refused and nothing is stored. This doesn't depend on the WTF folder
     names, which an upload doesn't carry.
5. **Beside Battle.net's data, never over it.**
   - Game data is its own table, one row per character. It never changes a Battle.net
     snapshot.
   - Each view says which source it shows, and how old it is.
   - Whether the game's newer level counts before the next sync is #186's call.
6. **Only the newest import is kept.**
   - This isn't data from Blizzard's API, so ADR 0034's 30-day rule doesn't apply. But
     there's no reason to keep history, so a new import replaces the old one.
   - What's stored is the parsed, validated data, not the uploaded file.
   - It belongs to the character: character deletion, account deletion and erase all
     remove it. The privacy notice lists it.
7. **A purpose-built parser, which never executes anything.**
   - It reads only what SavedVariables contain: assignments of tables, strings,
     numbers, booleans and `nil`, plus comments (`addon/SCHEMA.md` lists it). Anything
     else is an error naming the line and column.
   - **Why not a library:**
     - `lupa` runs Lua, so a hostile file could run code.
     - `slpp` and `luadata` have had no release since 2020 and 2021.
     - `luaparser` is maintained and runs nothing, but it parses all of Lua: a far
       bigger surface than these files need.
   - **Limits:** the file at most 1 MiB, nesting at most 16 deep, at most 50,000 values,
     strings at most 4 KiB.
     - A full character comes to roughly 100 KiB: about 160 bag slots, a few hundred in
       the bank, a 35-quest log. So 1 MiB leaves ample margin.
     - The upload's size is checked before parsing.
   - **Tests:** real files from the addon, and hostile ones. Property-based tests check
     that random tables round-trip, and that random bytes fail only with the parser's own
     error.
8. **The addon lives in this repo.** `addon/CharacterPlannerExport/` holds it, and
   `addon/README.md` documents a development junction into the AddOns folder. The Docker
   image copies named folders only, so the addon stays out of it.

## Consequences

- **#179 to #182** build the addon to `addon/SCHEMA.md`. They're Bryce's learning tasks;
  each verifies its APIs on Forever first.
- **#183** builds the parser to this ADR's subset and limits. **#184** adds the upload
  route, storage, migration and privacy notice.
- **The surname and region may not be readable** from the addon. Matching then rests on
  the selected character and the name.
- **Schema changes cost a version bump.** That's deliberate: the addon and the planner
  ship separately.
