# Test fixtures

`forever_*.json` are real WoW Forever Profile API responses for Brumboldt Doomlet,
captured by the spike on 2026-11-11 (`samples/20261111T185331Z`), with `_links` removed.
Only the response body is kept.

The account response (`/profile/user/wow`) is deliberately not here: it lists every
character on the account.

To refresh: run `uv run character-planner-spike`, then
`jq 'del(.. | ._links?) | .body' samples/<ts>/<kind>.json > tests/fixtures/forever_<kind>.json`.

`forever_item_*.json` come from the item probe (`samples/items-20261111T193134Z`):
the Dwarven Defender search (exact match present), the Flamefist Grips search (no exact
match: Forever-new item) and the item media response for Burnished Shield (3655).

`companion_item_270230.json` is the real Forever Companion `GET /items/270230` response
(Kindlegem Girdle) from `samples/companion-20261111T200041Z`.

`companion_dungeon_hall_of_thanes.json` stands in for `GET /dungeons/hall-of-thanes`: it is
built from the spec and the drop table printed on 2026-11-11 (level range and quests
unknown). Replace it with the real response:
`curl.exe -s https://forevercompanion.io/api/v1/dungeons/hall-of-thanes -o tests/fixtures/companion_dungeon_hall_of_thanes.json`.
Tests only assert the drop table, so they hold for the real file.
