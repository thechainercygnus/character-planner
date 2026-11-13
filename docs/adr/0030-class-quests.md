# 0030: A class quest checklist, with done marks set by hand

Status: accepted (2026-11-13)

## Context

Class quests unlock core abilities and are easy to miss while leveling: a Warrior's
Defensive and Berserker Stances (#8). Forever Companion's `GET /class-quests` lists them:
`id`, `class`, `level`, `name`, `faction`, `races`, `giver`, `location`, `reward` and
`essential`.

Checked on 2026-11-13:

- 44 quests across 9 classes; 8 are the Warrior's.
- The list's CDN cache ignores query strings, like `/items` and `/rares` (ADR 0004,
  0029): `?class=warrior` returned all 44.
- `races` is set only on the five level 10 Warrior stance quests, in lowercase with
  hyphens (`night-elf`). Blizzard's profile names races "Night Elf".
- No API says which quests a character has done.

## Decision

- `class_quests.py` fetches the list once per pool refresh, beside the rares, and merges
  each quest into `CompanionClassQuest` by id (migration 0006), so a filtered list served
  from the cache can't remove any.
- The checklist keeps the synced character's class, faction and race. Names are compared
  in Forever Companion's form ("Night Elf" becomes "night-elf"). An unknown faction or
  race rules nothing out.
- Each quest gets a status:
  - done: marked by hand;
  - missed: essential, at or below the character's level, not done;
  - now: at or below the level;
  - soon: within 5 levels;
  - later.
- Done marks are stored in `ClassQuestDone` (`PUT /api/class-quests/{id}`). Only ids
  Forever Companion has listed can be marked.
- The Plan tab lists the quests by status, and its tab shows how many are missed.

## Consequences

- Quests done before the app existed show as missed until they're ticked once.
- A quest Forever Companion renames keeps its id, and its done mark with it. A new id
  starts not done.
- An instance gets its class quests at the next pool refresh: the worker's daily run or
  the button.
