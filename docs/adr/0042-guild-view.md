# 0042: The guild view: opted-in members only, users on, roles from specs

Status: accepted (2026-11-14)

## Context

#18 lets guildmates plan dungeon runs together: who needs what from a dungeon, and which
dungeon is worth most to the group. That shows one person's characters to other people,
which Blizzard's terms (ADR 0034) allow only for the people using the app together, not
publicly (#42).

## Decision

Bryce chose the three options below (2026-11-14).

1. **Opted-in members only.**
   - A character opts into the guild its synced profile names (`guild.id`).
   - Once in, it sees every other opted-in member of that guild in the same region: their
     names, levels, specs, roles and upgrades.
   - Before opting in, a character sees only its guild's name, nothing about anyone in it.
   - A member who opts out, or whose newest profile names another guild, drops out of
     everyone's view.
   - A character's membership is its own row (`guildmembership`). Deleting the character
     deletes it.
2. **Users on only.** Without users (ADR 0037) there's one person, and a "guild" would only
   ever be their own characters. `/api/guild` answers 404 then, and the Guild tab isn't
   shown.
3. **Roles from each synced spec.**
   - The tree with most talent points is the spec, and `data/curated/roles.yaml` maps each
     class's specs to tank, healer or DPS.
   - The spec names are Forever's own, from Blizzard's talent-tree index: "Shadow Magic",
     "Elemental Combat", "Feral Combat".
   - Feral Combat counts as a tank, since bears tank dungeons.
   - Any member can set their own role, which wins.
4. **The group ranking adds up each member's own recommendations.**
   - Each member's needs come from their own weights, rules, targets and dismissals
     (`jobs.recommendations_for`), so a dungeon's value is what each would really take.
   - The members going are all of them by default, or the ones ticked.
   - Each dungeon lists who is within its levels, and the group is flagged if it has no
     tank or no healer.
5. **Guild-channel alerts** (#18's stretch) wait for #58's bot.

## Consequences

- **The privacy notice says it:** opted-in guild members see each other's characters,
  levels, specs and upgrades.
- **No extra access control.** The guild view reads other users' characters for display.
  Requests still resolve the asker's character through the signed-in user (ADR 0037), and
  the two-user route sweep covers both new routes.
- **Cost:** the view computes every member's recommendations on each request. That's fine
  for a guild's handful. A large instance would cache it.
