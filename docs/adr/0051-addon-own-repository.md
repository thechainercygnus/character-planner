# 0051: The addon has its own repository; the schema stays here

Status: accepted (2026-11-18). Amends ADR 0047, point 8.

## Context

ADR 0047 put the CharacterPlannerExport addon in this repository, under `addon/`. But the
addon and the planner ship separately: one is a release on GHCR, the other a folder
players drop into their AddOns. They're also built differently: the addon is Bryce's
Lua learning work (#177), while the planner has its own CI. Bryce moved the addon to its
own repository (2026-11-18).

## Decision

1. **The addon lives in
   [character-planner-export](https://github.com/thechainercygnus/character-planner-export).**
   - The repository's root is the addon folder, so a junction from the AddOns folder
     points at the clone itself.
   - Its issues moved there too (#179–#182, now that repository's #1–#4). The epic #177
     and the planner-side issues stay here. The roadmap (#25) lists the addon issues by
     their full names.
2. **The schema stays in the planner, at `addon/SCHEMA.md`.**
   - The planner's parser enforces the schema strictly, and its tests read the schema's
     example.
   - ADR 0047 has the planner learn a new version before the addon writes it. So the
     planner owns the contract, and the addon's repository links to it.
   - A schema change is still a version bump in a planner PR, made before the addon's
     release that writes it.
3. **Nothing else in `addon/` is tracked here.** Copies of the addon left over from
   before the move aren't the source of truth.

## Consequences

- **Two pull requests for a schema change:** one here (`SCHEMA.md`, the parser and its
  tests), then one in the addon's repository. Neither repository's CI sees the other.
  The schema example, which the planner's tests read, is the shared check.
- **Real files from the addon** become test fixtures here
  (`tests/fixtures/savedvariables/`), with nothing personal in them.
- **The dev junction** points at the addon's clone (Bryce's is
  `D:\WoW\AddOns\CharacterPlannerExport`), not at this repository.
