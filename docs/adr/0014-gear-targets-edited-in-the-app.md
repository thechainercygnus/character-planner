# 0014: Gear targets edited in the app, one list with pins

Status: accepted (2026-11-12). Replaces the pinned-target part of ADR 0012. Brackets are
replaced by per-target levels in ADR 0015; storage, editing and pins stand.

## Context

Gear targets lived only in `data/curated/gear_targets.yaml`. ADR 0012 added pins on the
Upgrades tab as a separate list in `ItemChoice`, which the Plan tab never saw. That left
two lists of targets with different behaviour.

## Decision

- **Storage:** the whole edited set lives in `StoredGearTargets` (one row, like
  `StoredTalentPlan`) and wins over the YAML until "Reset to defaults" deletes it. Every
  reader goes through `jobs.gear_targets`: Plan, Upgrades, summary and the item lookups
  after a sync.
- **Editing:** `PUT /api/targets` replaces the set and `DELETE /api/targets` resets it.
  `GET /api/targets` keeps its shape. Saving sorts brackets by level and sets each target's
  priority from its position. Slots must be equipment slots, levels 1–80, one bracket per
  level, and item names can't be blank.
- **Pins are targets with `pinned: true`.** "Make target" (`POST /api/targets/pins
  {item_id, slot}`) adds a pool item to the bracket for the character's level, pinned,
  with the pool's name and source. If no bracket starts at or below the level, one is
  added at it. An item that's already a target there ("Pin" on Upgrades) just gets the
  mark.
- **Unpin only takes the mark off.** "Unpin" (`DELETE /api/targets/pins/{item_id}`)
  unpins the item in whichever bracket it's in. It stays a target; the editor removes
  targets.
- **Only pinned targets are always listed** on the Upgrades tab, in any bracket, until
  worn. Other targets, including all of the YAML's, are only tagged. Upgrades stays a tool
  for finding gear you didn't know about, plus the few items you chose to keep in view.
  The Plan tab is where the whole plan, and stale targets, show.
- **Choices:** `ItemChoice` keeps dismissals only. Pins stored under ADR 0012 move into the
  current bracket at startup when the pool knows their slot, and are dropped with a
  warning otherwise.
- **Plan tab:** an "Edit targets" dialog adds, removes and reorders targets and brackets,
  and has a "Pinned" checkbox per target. Item names autocomplete from the pool, which
  fills in the item id and source. `GearPlan.targets_customised` drives the "customised"
  mark.

## Consequences

- Moving up a bracket doesn't change what Upgrades always lists; only pins do.
- Hand-entered item facts (stats, armor) are kept through edits, but the editor doesn't
  show them; they stay a YAML feature.
- #14 makes the stored targets per character.
