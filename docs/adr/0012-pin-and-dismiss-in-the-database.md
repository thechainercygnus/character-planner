# 0012: Pin and dismiss recommendations, stored in the database

Status: accepted (2026-11-12)

## Context

The Upgrades tab proposes gear from the item pool (ADR 0007). Steering it meant editing
YAML: add an item to `gear_targets.yaml` to flag it, or its id to `exclude_item_ids` in
`recommend.yaml` to hide it. Both should be one click. Stat weights (ADR 0005) and the
talent plan (ADR 0009) already set the pattern: the curated file is the default and edits
made in the app go in the database.

## Decision

- One `ItemChoice` row per item: `target` or `dismissed`, plus the item name so a hidden
  item can be listed after it leaves the pool. A new choice replaces the old one.
- Choices add to the files. They don't replace them: dismissed ids join `exclude_item_ids`,
  pinned ids join the `gear_targets.yaml` targets. The files can't be undone from the app.
- A pinned item is always listed for its slot, even below `per_slot` or `min_gain`, until
  it's worn or unpinned; `Candidate.pinned` says so. A pinned ring or trinket is listed once,
  in the slot it would replace first. Pins don't change the dungeon ranking.
- A pinned item still has to pass the usage rules (level window, armor, weapon types).
- `GET /api/choices`, `PUT /api/choices/{item_id}` (`{choice, name}`),
  `DELETE /api/choices/{item_id}`. Expanded upgrade rows get "Make target" / "Unpin" and
  "Never suggest"; hidden items are listed under the table with an undo.

## Consequences

- Pins don't appear on the Plan tab, which still reads `gear_targets.yaml` by bracket.
  Folding them in needs a slot and bracket per pin. That's left for later, if it's wanted.
- Stat weight presets (#11) can reuse the same split: defaults in YAML, choices in the DB.
