# 0008: Rebuild progress over time from the stored snapshots

Status: accepted (2026-11-11). Amended by ADR 0034 (#131): snapshots are deleted after
30 days, and older points are kept in `ProgressHistory` with only the date, level and
average item level. Score, stats and gear changes cover the last 30 days.

## Context

Every sync already stores the raw profile, equipment and statistics responses (ADR 0002).
That history can show how the character grows: level, item level, survivability, and
when each piece of gear changed.

## Decision

- `progress.py` reads the successful profile, equipment and statistics snapshots and
  groups those taken within 30 seconds of each other into one sync. A sync that lacks a
  kind keeps the last known one.
- Each sync becomes a point:
  - level
  - average item level (computed as in the header)
  - gear score: the sum of the equipped items' scores with the *current* stat weights
  - health, armor and stamina
- Consecutive syncs are compared slot by slot (by item id) for gear changes, with the
  score change, and by level for level-ups.
- Nothing new is stored. `GET /api/progress` rebuilds the history on each request.
- The frontend's Progress tab shows:
  - current-value tiles with the change since the first sync
  - one small chart per measure (no dual axes), with hover values and a table view
  - a change log

## Consequences

- History only exists for what was synced. Scheduled syncs (the homelab deploy) will
  fill it in without manual clicks.
- Changing the stat weights rewrites the gear score history. That keeps one consistent
  scale, but it's not "what the score was then".
- Rebuilding on every request is fine for hundreds of syncs. If history grows into
  the thousands, cache the points.
