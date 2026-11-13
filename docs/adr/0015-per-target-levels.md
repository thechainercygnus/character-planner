# 0015: Per-target levels instead of brackets

Status: accepted (2026-11-12). Replaces the brackets in ADR 0014.

## Context

Targets were grouped in level brackets copied from the guide. The Plan tab showed only the
current bracket, so the whole plan switched at once at a bracket's level, and the brackets
repeated what each item already knows about its own level. Upgrades and Dungeons place
items by level instead, so the app handled level two ways.

## Decision

- **One list.** `GearTargets` is a flat list of targets. A slot's order is its priority;
  saving and loading rank it.
- **A target's level** is the higher of its `level` (optional: when you plan to go for it)
  and the item's own level: the required level from Blizzard or Forever Companion, else
  the pool's quest or dungeon level. A target with no known level counts as reachable now.
- **Plan tab, per slot:** a slot's targets are sorted by level, then priority. The current
  target is the last one the character's level has reached, or the one being worn when
  that's further along. The next three are "coming up", with their level, source and score
  against what's worn. Slots whose targets are all above the level are listed apart.
- **When a target goes:** only when worn; the slot moves on to the next. A current target
  that scores below what's worn stays listed, marked "outgrown".
- **Pins** stay a flag on a target. "Make target" adds the item at the end of its slot with
  no level, so its own level places it.
- **Old data:** targets saved in brackets (the YAML before this, or edits stored under
  ADR 0014) are read as a flat list: each takes its bracket's level, and a slot keeps
  bracket order, then priority. The next save writes the new shape.
- **Editor:** targets are shown by slot, each with a level column whose placeholder is the
  pool's level for the item. "Add target" takes a slot.

## Consequences

- Nothing switches all at once on a level-up; each slot moves on by itself.
- Crafted and other far-off targets show up early, so you can prepare for them.
- "How far ahead" is three targets per slot, not a level window. #4 (look ahead) can build
  on this.
- The guide's bracket levels survive in `gear_targets.yaml` as each target's `level`.
