# 0016: Upgrades rules edited in the app

Status: accepted (2026-11-12).

## Context

`data/curated/recommend.yaml` decides what the Upgrades tab suggests: what the character
can wear (weapon, armor and off-hand types, the plate level, two-handers) and how items
are listed (levels ahead, per slot, minimum gain). It was the last preference that could
only be changed in a file, which isn't possible from the deployed container. Its
`exclude_item_ids` overlapped with "Never suggest" (ADR 0012).

## Decision

- **Storage:** the same pattern as weights, the talent plan and targets. The edited rules
  live whole in `StoredUsageRules` (one row) and win over the YAML until "Reset to
  defaults" deletes it. Every reader (Upgrades, Dungeons, Enchants) gets them through the
  `get_rules` dependency.
- **API:** `GET /api/rules` returns the rules, the YAML defaults, whether they're
  customised, and the types the editor can offer. `PUT` replaces them, `DELETE` resets.
- **Validation:** types must be ones the editor offers: the weapon types and armor classes
  seen in Forever Companion's item details, and for the off hand, shields, held-in-off-hand
  items (weapon type Miscellaneous) and one-handed weapons. Plate isn't an armor choice; it
  comes from the plate level, which can be blank for never. Numbers are bounded. Lists are
  saved in the editor's order without repeats.
- **Exclusions are dismissals.** `exclude_item_ids` leaves the YAML and the model; hiding
  an item is "Never suggest". The shipped list was empty, so nothing moves. A YAML that
  still has ids logs a warning and the ids are ignored, instead of being copied in on
  every start, which would bring back items you'd undone.
- **UI:** an "Upgrades settings" dialog on the Upgrades tab, beside Stat weights.

## Consequences

- #14 moves these rules into a per-character record, with what a character can wear
  coming from its class; the shape stays.
- #37's guest mode can reuse the rules model for a chosen class.
