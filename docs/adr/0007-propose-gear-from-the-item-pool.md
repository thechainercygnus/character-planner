# 0007: Propose gear from the item pool

Status: accepted (2026-11-11)

## Context

Phases A and B gave us stat-weight scoring (ADR 0005) and a pool of every dungeon drop
and dungeon quest reward with item details for the level window (ADR 0006). At level 18
that's about 340 items. `gear_targets.yaml` was hand-picked and can miss upgrades,
especially for slots left empty (neck, shoulders, a second ring, trinkets).

## Decision

- `data/curated/recommend.yaml` says what the character can and wants to wear:
  - usable weapon types (no wands)
  - armor classes (plate from level 40)
  - no two-handers while tanking, and only shields in the off hand
  - how many levels ahead to look
  - items to exclude
- `recommend.py` maps each item's own slot (Forever Companion's `slot`, e.g. "One-Hand")
  to equipment slots and scores every usable item with the current stat weights. It
  lists the biggest score gains over what's equipped, `per_slot` per slot.
  - Rings and trinkets fill the weaker of their two slots first. The stronger slot
    doesn't repeat the weaker slot's top pick.
  - Items a few levels out are listed but flagged as not wearable yet. An item without a
    required level uses its source's level instead. For a dungeon quest, that's the
    higher of the quest's pickup level and the dungeon's minimum, since the quest is
    done inside the dungeon.
  - Gains at or below `min_gain` (1.0) count as sidegrades and aren't listed.
- Dungeons are ranked by the sum of the best upgrade they hold for each slot. Only
  items wearable now count, and an item counts once.
- `gear_targets.yaml` stays as the hand-picked plan. Items it names are flagged
  "your target" in the recommendations.
- `GET /api/recommendations` serves this. The frontend splits the page into four tabs:
  - **Upgrades:** compact rows that expand for details.
  - **Dungeons:** one card per dungeon.
  - **Plan:** `gear_targets.yaml`.
  - **Character:** equipped gear, stats, talents and professions.

  The selected tab is kept in the URL hash.

## Consequences

- Recommendations follow the weights, so tuning them changes picks immediately.
- Items without item details (not fetched yet, or 404 at Forever Companion) can't be
  scored. They are counted as unscored rather than guessed.
- Zone quest rewards, vendor and crafted gear aren't in the pool, so the engine can't
  propose them. `gear_targets.yaml` covers those.
- Usability rules are per character. Another class or spec needs its own
  `recommend.yaml` and weights.
