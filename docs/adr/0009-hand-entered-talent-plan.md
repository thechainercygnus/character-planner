# 0009: Hand-entered talent plan, compared after each sync

Status: accepted (2026-11-11)

## Context

The specializations snapshot lists only the talents with points in them, with their
ranks. No API we use gives the Forever talent tree (talents, tiers, max ranks), and
Forever's tree differs from Classic: Anticipation is "+4 Defense" at rank 1. The Wowhead
Forever build guide describes builds in prose, with no calculator links and no point order
to import.

## Decision

- A plan is an ordered list of steps: "talent up to rank". A talent can repeat with a higher
  rank later. Steps that don't raise the rank are ignored.
- The default lives in `data/curated/talent_plan.yaml`, seeded with the 9 points spent at
  level 18. Edits from the app are stored in `StoredTalentPlan` and win over the file
  (as stat weights do, ADR 0005).
- Points follow Classic: first point at level 10, then one per level. This matches the
  synced data (9 points at 18). Each step reports the level its last point needs.
- `compare()` gives per-step state (done, partial, pending), the next point with its level,
  and points spent beyond or outside the plan. Names match case-insensitively.
- `GET /api/talents`, `PUT /api/talents/plan`, `DELETE /api/talents/plan`. The Character tab
  shows the plan with an editor dialog.

## Consequences

- Plan names must match in-game talent names. A typo shows up as "off plan" rather
  than failing silently.
- No validation against the real tree (max ranks, tier requirements) until a source for
  it exists. Ranks are capped at 10 as a sanity bound.
- Importing a Wowhead calculator link stays open: it needs a decodable build string first.
