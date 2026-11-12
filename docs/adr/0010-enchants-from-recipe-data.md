# 0010: Enchants from Blizzard recipe data, gaps filled by hand

Status: accepted (2026-11-12)

## Context

Issue #20 planned a hand-written enchant list. The recipe probe (2026-11-12) showed the
static Forever API serves every profession's skill tiers, categories and recipes, and
Enchanting recipes carry the in-game description ("...increase the wearer's Stamina by
3."). Recipes have no skill or level requirement. Items that enchant gear (scopes, armor
kits, weapon stones) have recipes without a description, and neither Blizzard's item
endpoint (404, ADR 0003) nor Forever Companion (404 for all 45, 2026-11-12) serves them.
Forever Companion has only 5 of the 146 reagents, so reagent item levels rarely give a level.

## Decision

- The catalog is Blizzard's recipe data for Enchanting, Engineering, Leatherworking and
  Blacksmithing, stored raw in `RecipeData` for 30 days. Slots come from the category
  (from the name for Season of Discovery recipes, which are excluded by default).
- Effects are parsed from descriptions. Procs, speed and skill bonuses stay unscored.
- `data/curated/enchants.yaml` fills the gaps:
  - `reagent_levels`: the level from which a material is common (Strange Dust 1, Soul
    Dust 21...), from Classic's disenchanting and mining tables. An enchant's estimated
    level is the highest of its reagents'; Forever Companion's item level is the fallback.
  - `crafted_effects`: effects of scopes and kits, by crafted item id, copied from the game.
- Enchants on the character's own gear ("Enchanted: Scope (+1 Damage)", with the source
  item) teach the crafted item's effect and win over the curated list.
- Per slot, `advise()` scores each enchant that fits the item worn (shield enchants only on
  shields, no two-handers for a tank, scopes on bows, guns and crossbows) with the stat
  weights: flat weapon damage counts as damage ÷ weapon speed DPS. The gain is over the
  enchant on now. Enchants more than `levels_ahead` past the character's level, or with no
  estimate, are left out; a recipe the character knows is always in reach and flagged.
- Weapon stones are temporary and not recommended. Prices are out of scope.
- `GET /api/enchants/recommendations` serves it; the Upgrades tab shows an Enchants section.

## Consequences

- The level estimate is approximate and Classic-based. Wrong bands show as enchants listed
  too early or too late; fix them in the YAML.
- Scopes and kits rank only once their effect is known: from the gear, or entered by hand.
- Unweighted stats (Block %, Dodge %) score 0 until they get a weight.
