# 0033: Enchant data corrected in the app, on top of the shipped file

Status: accepted (2026-11-13)

## Context

`data/curated/enchants.yaml` fills the gaps Blizzard's recipe data and Forever Companion
leave (ADR 0010):
- each enchanting material's level band (Classic's);
- the effects of scopes and armor kits;
- how many enchants to list per slot.

Fixing a value meant editing the file and restarting, which a deployed container doesn't
allow (#36). A release with better bands should still reach values nobody corrected.

## Decision

- **Storage:** corrections live in one JSON row, `StoredEnchantCorrections` (migration
  0008), as the Upgrades rules do (ADR 0016). They cover a material's level by item id,
  a crafted enchant's effect by crafted item id, and `per_slot`.
- **One place applies them:** `get_enchant_data` puts them on top of the YAML, so the
  catalog, the advice and anything later see the same data. Each value is either
  corrected or shipped; a value never corrected follows the YAML as it ships.
- **Precedence:** effects read from the character's own gear still win over both, as
  real game text (ADR 0010).
- **Every material reports its level and source** (`corrected`, `shipped` or `item` for
  Forever Companion's item level). Advice lists the crafted enchants in reach with no
  known effect, so they can be filled in, plus `per_slot` and whether it's corrected.
- **API:** `GET /api/enchants/corrections` (corrections, shipped values and the effect
  names allowed); `PUT` or `DELETE` on `.../materials/{item_id}`,
  `.../crafted/{item_id}` and `.../per-slot` to set or reset one value. Effects must use
  a name the effect parser knows and be above 0. Levels are 1 to 60, `per_slot` 1 to 10.
- **In the Enchants section:** each pick has a "Materials and effect" disclosure to edit
  or reset levels and effects, the heading picks the number per slot, and a list collects
  the effects still missing. Corrected values carry a "corrected" tag.

## Consequences

- A correction outlives a better shipped value for the same key until it's reset.
- Corrections are per instance (one character, until #16 adds users).
