# 0025: Talent trees from Blizzard, and a visual planner

Status: accepted (2026-11-13). Replaces the hand-entry parts of ADR 0009. The plan's
shape and the comparison with synced talents stand.

## Context

ADR 0009 said no API gives Forever's talent tree, so plans were typed as talent names and
ranks. Blizzard's game data does have them, in the static-forever namespace:
- `/talent-tree/index` names each class's tree;
- `/talent-tree/{id}` lists every node with its prerequisites (`locked_by`);
- `/talent-tree/{id}/playable-specialization/{spec}` gives each node's grid place and its
  ranks, with tooltip text;
- `/media/spell/{id}` gives the icons.

Every node in the 6 Warlock and Warrior trees checked is one talent with 1 to 5 ranks.

## Decision

- **Catalog:** the synced class's trees and talent icons are fetched with an app token and
  stored raw (`TalentTreeData`, `SpellIcon`; migration 0003).
  - They're parsed on read into spec trees of nodes: row, column, ranks, prerequisites as
    talent ids, icon.
  - Columns count across the class in the data, so each tree's are made 1-based.
  - They load on the first sync (ADR 0024's missing-data load) and weekly in the worker,
    under a "talents" lease. `GET /api/talents/tree` serves them; `POST
    /api/talents/refresh` fetches them again.
- **Plans keep their shape** (ordered steps, a talent up to a rank) and gain the talent's
  **id**.
  - Older plans get ids from names when read, and when saved.
  - Synced talents carry ids and come from every tree, not only the main one, so hybrid
    builds compare whole.
  - Matching is by id, by name otherwise.
- **Rules,** checked on save (422 with the reasons) and in the browser before a click
  lands:
  - ranks rise, up to the talent's max;
  - a prerequisite is at its max rank first;
  - a row opens after **5 points in its tree**. That's Classic's rule; it isn't in the
    data, but the synced Warrior (9 points) and a 45-step plan both fit it.
- **Planner:** the Character tab shows the three trees as grids, with icons, each talent's
  planned and synced ranks, and locked talents dimmed.
  - **Edit plan** makes them clickable: click adds the next point at the end of the order,
    right-click or shift-click takes a talent's last point off.
  - A refused click says why.
  - The order of points lists the levels they're spent at.
  - The text editor stays only for while the trees aren't loaded.

## Consequences

- Classes without a shipped plan (#80) get the real trees, empty, instead of a text box.
- If Forever turns out to use a different points-per-row rule, `POINTS_PER_ROW` (in
  `talent_trees.py` and `talentRules.ts`) is the one thing to change.
- #41 moved the planner, as it is, to its own Talents tab. Character shows talents as spent,
  read-only.
