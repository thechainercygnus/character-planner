# 0013: Stat weight presets

Status: accepted (2026-11-12). Extends ADR 0005.

## Context

There was one editable weight set (ADR 0005). Leveling tank, dungeon tank and solo DPS
value stats differently, and switching meant retyping weights. ADR 0012 set the pattern
for this: curated files are the defaults and the database holds what's edited in the app.

## Decision

- **Shipped presets:** `stat_weights.yaml` is "Leveling tank" (key `leveling-tank`).
  `weight_presets.yaml` ships "Dungeon tank" and "Solo DPS", with their reasoning in
  comments. Stats a preset leaves out take the Leveling tank weight.
- **Stored presets:** one `WeightPreset` row per preset.
  - A `shipped=True` row holds edits to a shipped preset under the same key. Deleting
    the row is "Reset".
  - A `shipped=False` row is a preset of your own, made with "Save as". It can be renamed
    and deleted. Shipped presets can't be renamed or deleted.
- **Active preset:** `ActiveWeightPreset` (one row) names the preset that scores
  everything. With no row, or if that preset was deleted, Leveling tank is active.
- **Migration:** at startup, a `StoredWeights` row from before presets becomes Leveling
  tank edits and is deleted, so nothing is lost.
- **API:** `/api/weights` keeps its shape and acts on the active preset, and adds `preset`
  and `presets`. New routes:
  - `PUT /api/weights/active` switches presets.
  - `POST /api/weights/presets` is "Save as". It copies the active preset when no weights
    are sent.
  - `PATCH` and `DELETE /api/weights/presets/{key}` rename and delete.
  - Names are 1–40 characters and unique, ignoring case.

## Consequences

- Every scored view (Upgrades, Dungeons, Plan, Progress gear score, enchants, summary) uses
  the active preset without changes of its own.
- Progress gear scores are recomputed with the active preset. Switching presets changes the
  history's numbers too, not just the latest ones.
- Presets are global for now. #14 makes them per character.
