# 0031: Crafted gear from known recipes, and curated profession ranks

Status: accepted (2026-11-13)

## Context

Professions showed as bare skill numbers, and the item pool didn't know crafted gear
(#10). ADR 0010 reads Blizzard's profession, skill-tier and recipe data for enchants; the
open question was whether other recipes lead to crafted items with stats.

Checked on 2026-11-13 against the Forever static namespace:

- The character's professions snapshot lists each profession's `skill_points`,
  `max_skill_points` and `known_recipes` (id and name). Brumboldt's Engineering knows 19.
- `GET /data/wow/recipe/{id}` names the `crafted_item`; nothing says the skill needed to
  craft it. Each profession has one skill tier (1 to 75 by its own fields), so tiers
  can't place recipes by skill either. "Requires Engineering (30)" on a bomb is the skill
  to use it, not to make it.
- `GET /data/wow/item/{id}` has the crafted item's stats, armor, weapon damage, required
  level and item level under `preview_item`, shaped like an equipped item. Flying Tiger
  Goggles read +4 Stamina, +4 Spirit, 27 armor, item level 20: the same as worn.
- Forever Companion has no crafted items (`/items/{id}` 404s for them).
- Neither API publishes trainer ranks (Journeyman, Expert...) or when they're trained.

## Decision

- **Crafted gear comes from known recipes.** A recipe the character knows can be crafted,
  so no skill is needed. After each sync (best effort, like the item catalog), the
  recipes it knows and the items they make are fetched and kept 30 days. They're stored in
  `CraftingRecipe` and `BlizzardItem` (migration 0007), 404s included. These are apart
  from `RecipeData`, which keeps the enchant catalog's recipes and their categories.
- **Each equippable crafted item joins the pool.** It becomes a `PoolSource` of kind
  `crafted` with its profession and recipe. Its Blizzard details are mapped onto the
  item details the pool already scores. Forever Companion's details win if it ever lists
  the item.
- **Guest mode gets none**, since it reads no character data (ADR 0017). `pool_view`
  takes the crafted items only from callers that serve the synced character.
- **Trainer ranks are curated data** in `data/curated/professions.yaml`, using Classic's
  values: Journeyman at 50 skill and level 10, Expert at 125 and 20, Artisan at 200 and
  35. Notes cover the secondary professions' book and quest ranks. The rank comes from
  the skill cap.
- **The Progress tab lists each profession:** skill against its cap, the next rank and
  what it still needs, and the gear its known recipes make.

## Consequences

- Recipes not learned yet aren't candidates. Placing them needs the skill to craft each
  one, which neither source gives; a curated list could add that later.
- If Forever changes a rank's thresholds, `professions.yaml` needs the edit.
- A sync now makes up to two requests per new known recipe, and none once they're cached.
