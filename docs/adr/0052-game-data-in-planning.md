# 0052: Game data in planning: owned items, newest wins, quest progress

Status: accepted (2026-11-18)

## Context

ADR 0047 kept the addon's game data beside Battle.net's, never over it, and left to #186
how planning uses it. Bryce decided (2026-11-18):
- items in the bags or bank are flagged "owned, not equipped";
- quest progress feeds the quest-reward views and Look ahead;
- where the two sources disagree, the newest wins, with a label saying which was used.

The first real file (addon 0.2.0) settles what's there to use:
- the header's level, with the file's capture time;
- the bags;
- the bank, once it's been opened;
- the quest log;
- the ids of completed quests.

There's no equipped gear in the file, so Battle.net stays the only source for what's worn.

## Decision

1. **Owned items are flagged, never hidden.**
   - An upgrade, a dungeon's drop, a gear target or a Look ahead target that's in the
     bags or bank carries `owned`: where it is, how many, and when that place was
     recorded.
   - The app shows it as "owned: in your bags", so the advice becomes "go and get it".
   - Rankings and gains don't change. The item still beats what's worn, and the player
     may want it for another slot or character.
   - An item in both places counts as in the bags: they're nearer, and their snapshot is
     newer.
   - A reached target is worn, so it's never flagged.
2. **The level: newest wins, per value.**
   - The game's level replaces the last sync's only when the file was captured after
     that sync. Each view that uses the level says which source it came from, and how old
     it is.
   - Only the level has two sources. Equipped gear has one: the addon doesn't record it.
3. **Quest progress rides on the quests the planner already describes.**
   - A quest-reward source, and each step of its chain, shows its log progress when the
     quest is in the log. It shows done when the quest's id is among the completed ones.
4. **Class quests stay ticked by hand.**
   - Forever Companion's class quests have a stable string id and no game quest id
     (`docs/vendor/`, `ClassQuest`), so the completed ids can't be matched to them.
   - They can be ticked from the game once Companion carries quest ids, or a curated map
     exists.

## Consequences

- **Nothing changes without an import:** every flag is empty, and the level stays
  Battle.net's.
- **A stale file can't outvote a newer sync:** times decide, not sources. A file captured
  before the last sync shows its data, but doesn't change the level.
- **#186 ships in three PRs:** owned items, the level, then quest progress.
