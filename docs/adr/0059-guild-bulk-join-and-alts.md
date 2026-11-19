# 0059: Joining a guild with several characters, and alts as one player

Status: accepted (2026-11-20). Amends ADR 0042.

## Context

A character joined its guild's view one at a time, from the Guild tab while it was the
selected character. A player with alts switched to each in turn. A player in several
guilds switched character to see each one. And a player's alts counted as separate
members, so the ranking could count one person twice (#215).

## Decision (Bryce, 2026-11-19)

1. **Join with several at once,** from the Guild tab or the account page:
   - `PUT /api/guilds/members` joins some of your characters in one guild and leaves with
     others.
   - It's still per character underneath (ADR 0042): each one's data is shared
     deliberately, and you leave with any one.
   - Only your own characters, and only ones in that guild, by their newest profiles.
     Anything else is a 404, checked before anything changes.
2. **Shared alerts** (ADR 0046): the bulk join can set the same shared alerts for each
   one joining. They stay per character afterwards.
3. **A guild picker:** the Guild tab lists every guild your characters are in
   (`GET /api/guilds`). It opens on the selected character's guild.
   - Each guild is seen through one of your characters there, chosen by `X-Character-Id`:
     the selected one if it has joined, else one that has, else any.
4. **Alts are grouped only on opt-in,** per player and per guild (`GuildAltGrouping`):
   - **Off (the default):** your characters are separate members, and nothing the guild
     sees links them. The server doesn't stop two of them "going" either, since refusing
     would reveal the link.
   - **On:** they share a `player` number, which belongs to that view alone and never
     names the user. "Going" keeps one character per grouped player: by default the
     viewing character if it's theirs, else their highest level. So the ranking and the
     missing-role check count the player once.
   - **A grouped player with one character in the view** shows no number: it would tell
     nothing.

## Consequences

- **Your data:** the grouping choice is part of your data. It's in your export, and deleted
  with your account.
- **Deep links:** `#guild` used to fall back to Upgrades on load, because the tab list
  gained Guild only after `/api/me` answered. `useHashTab` now reads the hash again when
  its tabs change.
