# 0060: Builds

Status: accepted (2026-11-20). Amends ADR 0042: a build's role comes before the spec's.

## Context

A character's stat-weight preset (ADR 0013) and talent plan (ADR 0009) were chosen
separately, and the guild guessed its role from the synced spec (ADR 0042). All three say
the same thing: what the character is for (#216).

Suggesting talents from stat weights isn't possible on Blizzard's data. The trees give
talent names and description text, not numbers to score against weights.

## Decision (Bryce, 2026-11-19)

1. **A build is a curated bundle:** a weight preset, a role (tank, healer or DPS), and
   optionally a talent order.
   - The Warrior's are in `data/curated/builds.yaml`; every other class has a `builds:`
     list in its class file.
   - Each build must name a preset its class ships. A typo fails at load.
2. **Every class has builds** made from its existing presets, each with its role. Only the
   Warrior's carry talent orders for now:
   - **Protection, for leveling and for dungeons:** 51 points to Shield Slam, starting
     with the shipped plan's points.
   - **Arms, for leveling:** 31 points to Mortal Strike, then Fury.
   - Claude drafted them for Forever's own trees (#88). A test checks them against the
     tree rules. Bryce reviews them, and corrections are edits to the YAML.
3. **Picking a build sets its pieces:**
   - its preset becomes the active one;
   - its talent order, if it has one, becomes the talent plan, so the planner's next point
     is the build's next point;
   - it's stored per character (`CharacterBuild`).

   The picker warns that a talent order replaces the plan before you follow it.
4. **Pieces stay editable.** Editing the preset's weights, switching preset, or changing
   the plan shows the build as "customised" in that piece. Picking the build again sets
   the talent plan again. Edits to the preset's weights are kept, and shown.
5. **One build per character,** switched by hand. Builds don't stage by level.
6. **The guild view's role** is the member's own choice there, then the build's role, then
   the synced spec's (amends ADR 0042).
7. **Where it's picked:** the Character tab, and each character's row on My account (#217).

## Consequences

- **The build is the character's data:** erased, deleted and exported with the character
  (`characters.OWNED`).
- **Upgrades rules per build** (such as dual wield from a given level) aren't part of a
  build yet. They can be added to the same YAML when one needs them.
- **Talent orders for the other classes** need Forever's trees for each class, as the
  Warrior's did. They come one class at a time.
