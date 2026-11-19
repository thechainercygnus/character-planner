# 0054: The Professions tab's recipe book

Status: accepted (2026-11-19). Extends ADR 0031.

## Context

ADR 0031 fetched only the recipes a character knows, for crafted gear. The Professions tab
(#226) also lists the recipes a character hasn't learned. Blizzard's Forever static data
has, per profession, one skill tier listing every recipe by category, with id and name
only. A recipe's crafted item, which is its Wowhead link, takes one more call per recipe.
No recipe has a skill requirement.

## Decision

1. **The tier comes from the snapshot's ids.** The professions snapshot names each
   profession's id and its tier's id, so the refresh fetches
   `/profession/{id}/skill-tier/{tier}` directly, with no walk of the profession index.
   It's kept raw in a new shared table, `SkillTier`.
2. **Every listed recipe is looked up,** and kept raw in `CraftingRecipe` beside the known
   ones (a 404 is cached as not found). The enchant catalog's `RecipeData` counts as
   looked up too. Both are shared game data, refreshed after 21 days and deleted at 30
   (ADR 0034). `SkillTier` and `CraftingRecipe` are in `erase.SHARED`.
3. **In the background, after a sync:** the API's sync, the queued sync and the worker's
   scheduled one all start it when something is missing, under one lease, `recipes`,
   which the status bar shows. Tiers come first, then the recipes they list.
4. **Crafted gear stays the known recipes'.** The crafted-items step fetches item details
   only for what known recipes make, though the recipe cache now holds more.
5. **Links** (Bryce, 2026-11-19): a looked-up recipe links to its crafted item. One not
   looked up yet, or one that makes no item, links to Wowhead's search for its name
   (`links.search_url`), which finds both the item and the recipe.
6. **Season of Discovery** recipes are flagged by their category, and hidden in the tab
   unless asked for (Bryce, 2026-11-19).
7. **No skill levels.** The tab says so. The addon may supply them later from trainer
   windows (thechainercygnus/character-planner-export#5), after a schema version bump.

## Consequences

- **The first sync after a profession is added** takes a few hundred calls, for example
  275 for Engineering, under the upstream budget (ADR 0040). The tab lists known recipes
  until the tier is cached, and links by search until each recipe is.
- **The Progress tab no longer shows profession milestones:** they moved to the
  Professions tab, above the recipes.
- **The recipe cache grows with the professions tracked,** not with the characters: it's
  shared by every character with that profession.
