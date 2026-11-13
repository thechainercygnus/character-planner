# 0023: Shipped defaults per class

Status: accepted (2026-11-13). Pulled ahead of #14 and #15 so a Warlock can beta test.

## Context

Every shipped default assumed a Protection Warrior: the usage rules, the stat weights, the
gear targets and the talent plan. Syncing, the pool, scoring and alerts already worked
for any class, and the synced profile names the class.

## Decision

- **Defaults are chosen by the synced character's class** (`classes.current_defaults`),
  read from the latest profile snapshot. They cover the usage rules, the weight presets,
  the gear targets and the talent plan. Edits made in the app still win until reset.
- **Where they live:**
  - The Warrior's are the original files in `data/curated/`, unchanged.
  - Every other class has `data/curated/classes/<class>.yaml`, with its usage rules,
    weight presets, and optionally targets and a talent plan.
  - The Upgrades tuning (levels ahead, per slot, minimum gain) is shared from
    `recommend.yaml`.
  - A class's first preset is its default. Later presets only list what they change.
- **Unknown cases get the Warrior's defaults,** with a warning: before the first sync,
  and for a class with no file yet.
- **No curated targets or talent plan** for the other classes yet. They start empty and
  are built in the app's editors. Showing a Protection plan to a Warlock would be wrong.
- **The usage rules gained two fields** for what Warrior rules never needed:
  - `mail_from_level`, for Hunters and Shamans at 40;
  - `two_hand_types`, because a Warlock wields staves but not two-handed swords.

  Held-in-off-hand items with no weapon type count as Miscellaneous.
- **Equip bonuses count as stats.** Forever writes most of them as "Equip: +N Stat" (Spell
  Power, Spell Damage, Healing, Attack Power). Blizzard lists the same bonuses among an
  equipped item's stats under the same names, as with Attack Power. Without this, caster
  gear scored as if it had no spell power.
- **Guest mode offers every supported class,** each with its own presets.
- **Data honesty:** proficiencies are Classic's, marked in each file to be corrected where
  Forever differs. Weights are labelled rough starting points.

## Consequences

- Adding a class is one YAML file and a test. All nine of Forever's classes (its talent
  tree index) have one since #80's second PR, with presets per role (leveling, then tank,
  healer or dungeon DPS where the class has them).
- Dual wielders (Rogues, Hunters) list one-hand weapon types in `off_hand_types`, so a
  one-hand weapon competes for the off hand too. The Warrior's `[Shield]` keeps its
  one-handers in the main hand.
- Edits made in the app are global, so on one instance they belong to the one tracked
  character. #14 makes them per character.
- A Warrior's equip bonuses (Attack Power, Defense Rating) now count for pool items too,
  as they already did for equipped gear, so some Warrior scores shift.
