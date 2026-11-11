# Test fixtures

`forever_*.json` are real WoW Forever Profile API responses for Brumboldt Doomlet,
captured by the spike on 2026-11-11 (`samples/20261111T185331Z`), with `_links` removed.
Only the response body is kept.

The account response (`/profile/user/wow`) is deliberately not here: it lists every
character on the account.

To refresh: run `uv run character-planner-spike`, then
`jq 'del(.. | ._links?) | .body' samples/<ts>/<kind>.json > tests/fixtures/forever_<kind>.json`.
