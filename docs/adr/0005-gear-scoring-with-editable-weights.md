# 0005: Score gear with stat weights the player can edit

Status: accepted (2026-11-11)

## Context

Item level alone misjudges gear: Direhammer Leggings are 5 item levels above the equipped
Stormwind Guard Leggings but leather, with less armor. Existing rankings (ForeverDB BiS,
Wowhead's Forever Gear Planner, Timesaver lists) rank for a generic spec, don't know the
character, and offer no API. This is phase A of a recommendation engine: score the
targets we already list. Later phases grow a local item pool and let the engine propose
targets, with gear_targets.yaml as pins and overrides.

## Decision

- `score(item) = sum(stat x weight) + armor x weight["Armor"] + DPS x weight`, with
  "Weapon DPS" for melee slots and "Ranged DPS" for the ranged slot. Bonus armor lines
  count as armor.
- Defaults for a leveling Protection Warrior live in `data/curated/stat_weights.yaml`,
  with the reasoning beside them. They are heuristics to tune, not simulation results.
- Edits are made in the app (`PUT /api/weights`), stored in `StoredWeights`, and merged
  over the defaults so new default stats still get a weight. `DELETE /api/weights` resets.
- A target's verdict uses its score gain over the equipped item when both have stat data
  (sidegrade within +-1.0), and falls back to item level otherwise. Each row says which
  basis it used. Rows sort by score gain; rows without a score keep priority order.

## Consequences

- Rankings respond to the player's own priorities immediately.
- Targets known only by item level (Blizzard search without Companion data) can't be
  scored; they show an item-level verdict until stats arrive.
- Weights apply to every slot alike; set bonuses, on-use effects and proc items are not
  scored.
