# 0032: A look-ahead built from the views the app already makes

Status: accepted (2026-11-13)

## Context

#4 asked what the next few levels bring. Its draft scope was confirmed on 2026-11-13:

- **What:** dungeons that open, gear targets that come into reach, talent points, class
  quests (#8) and profession ranks (#10).
- **Where:** the top of the Plan tab.
- **How far:** 5 levels by default, adjustable from 1 to 10.

Each of these already has its own logic and view: the gear plan's levels (ADR 0015),
the talent plan's points (ADR 0009), the class quest checklist (ADR 0030), profession
ranks (ADR 0031) and the dungeons' level ranges (ADR 0006). A second copy of any of those
rules would drift from the tab that shows it.

## Decision

- `lookahead.py` takes those views and lists, per level after the character's, what
  arrives there. It works out no levels of its own:
  - a dungeon at its minimum level, for the character's faction (Forever Companion's
    `access`, now kept on `Dungeon`), skipping announced dungeons and tagging ones not
    open yet (`betaLocked`);
  - a gear target at its level in the gear plan's upcoming targets, with its score gain
    and whether it's pinned;
  - each talent point at its level, named from the plan, or "Talent point" once the plan
    has run out;
  - a class quest at its level, unless marked done, tagged when essential;
  - a profession rank at its trainer level, with the skill still needed.
- `GET /api/look-ahead?levels=N` (1 to 10, default 5) returns the levels that have
  something on them, never past level 60.
- The Plan tab's "Coming up" section shows it. The chosen range is kept in the browser
  (`localStorage`): a per-browser convenience, not stored data.

## Consequences

- When a rule changes in one view (say, how a target's level is worked out), the
  look-ahead follows without changes.
- Gear targets show only as far as the gear plan lists them: the next few per slot.
