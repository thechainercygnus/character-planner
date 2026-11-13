# 0028: Quest chains from the dungeon data, steps described where Forever Companion can

Status: accepted (2026-11-13)

## Context

Quest-reward upgrades (#7) often sit at the end of a chain, and the app only named the
final quest. Forever Companion's `Quest` has `prerequisites`: the quests to do first,
earliest first, each step's quests (`{ questId, name }`) done side by side. The dungeon
detail payloads already stored (ADR 0006) carry them.

Checked on 2026-11-13 against all 30 stored dungeons:

- 125 dungeon quests have prerequisites. Each lists the whole chain, not just the quest
  before it, so building a chain needs no more requests.
- They name 134 distinct step quests. 31 are dungeon quests, described in the stored
  dungeon data.
- `GET /quests/{questId}` serves only dungeon and elite quests, as the spec's list
  description says. Of the other 103 steps, 12 are elite quests (200, with level, zone and
  usually a giver); 91 are ordinary zone quests and answer 404.

So the issue's plan to fetch every step's giver and location can't be met: about two
thirds of steps are only ever named.

## Decision

- `dungeons.py` keeps each reward quest's prerequisites, and every quest a dungeon lists
  as a described `QuestStep` (`quests.py`).
- `build_pool` gives each quest source its quest, described, and its chain. A step is
  described from any stored dungeon's quests, else from a quest fetched by id, else
  carries just its id and name.
- The pool refresh looks up, by id, only the steps of in-window rewards that no dungeon
  describes. Responses go in `CompanionQuest` (migration 0004), 404s included as
  `found=False`, kept 7 days like item details, paced and stopped at a 429 like every
  Forever Companion batch.
- A step with no description links to `https://www.wowhead.com/forever/quest={id}`, the
  form of every quest link in Forever Companion's data.
- An item's `effective_level` counts the chain: a quest source opens at the highest of
  its pickup level, the dungeon's minimum and every described step's pickup level.
- Expanded upgrade rows list the chain in order, then the reward's quest, each with its
  level and giver or place where known.

## Consequences

- Most chains show a step or two as names with a Wowhead link; giver and location appear
  when Forever Companion adds those quests, within a week of it doing so.
- A chain whose only level-setting step is an undescribed zone quest can still put an
  item a little early. The reward quest's own pickup level usually covers it.
- A first refresh adds a few dozen quest requests at most, inside the existing pacing.
