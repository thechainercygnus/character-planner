# 0063: Public character pages

Status: accepted (2026-11-22). Replaces ADR 0034's point 4.

## Context

ADR 0034 kept a public, Armory-style page (#42) blocked until Blizzard confirmed in
writing that one is allowed. Its licence grant, "distribute the Data to end users for
their personal use via Your Application" (§2), gives no express right to public display.
That was the cautious reading.

Bryce reread the same terms (the Blizzard Developer API Terms of Use, last updated
1 October 2019) on 2026-11-22. Two passages ADR 0034 didn't weigh point the other way:

- §2, physical products: "The Data should be dynamically available to the public and
  should not be integrated into any physical product." The terms expect Data in front of
  the public, as long as it stays deletable.
- §3: the licensee grants Blizzard the right "to distribute and publicly display" the
  Application "and the Data compiled and arranged by it".

Anyone who opens a page a player chose to share is an end user, viewing it for their own
use. The terms' real limits are on money (§2), on retention (30 days), on deletion when a
player asks (§11.3), and on credit (§2). An opt-in page meets all four.

This is a reading by the project, not legal advice.

## Decision

1. **Public pages are allowed.** Bryce chose this on 2026-11-22, and #42 is no longer
   blocked. Every other point of ADR 0034 stands.
2. **Opt-in per character, by its owner.** Off by default. Turning it on makes a random
   token: 24 bytes from `secrets`, 32 URL-safe characters. Turning it off deletes the
   token. **New link** replaces it. Either way the old link stops working at once. One
   link per character.
3. **The token rides in the link's fragment** (`/#public=<token>`), which browsers don't
   send to the server. The page posts it in a request body
   (`POST /api/public/character`), so it never reaches an access log. The route needs no
   sign-in. It answers 404 for an unknown, old or malformed token, with
   `Cache-Control: no-store` and `X-Robots-Tag: noindex`.
4. **The token is stored as is, not hashed.** Unlike an invite (ADR 0057), it isn't a
   one-time secret: the owner has to be able to copy the link again later. It grants
   only what the owner already chose to publish.
5. **What a page shows** is the last sync's snapshot: the header (name, level, race,
   class, guild, item level), spec and spent talents, equipment, stats and professions.
   `PublicCharacter` names each field, so a field added to the owner's view isn't
   published by accident.
6. **What it never shows:** plans, targets, weights, rules, dismissals, sync history,
   game data from the addon (its level included), tokens, the Battle.net account, the
   owner's other characters, and anything of the owner's settings.
7. **Read from the database only.** Viewing never calls Blizzard or Forever Companion.
   The 30-day rule applies unchanged: when the snapshots go, the page shows nothing until
   the next sync. Deleting the character, or the account, deletes the page.
8. **Credit stays on it.** The page has the footer that names Blizzard and Forever
   Companion, like every other page.

## Consequences

- With users on, the public route is the one place a stranger sees a user's data. It's
  only there when the owner turned it on, and only the fields in point 5.
- The privacy notice says who can see a public page and how to stop it.
- The guild view (#18) could link members' public pages. That's left for later.
- If Blizzard says otherwise, or its terms change, this record is revisited and pages can
  be turned off for everyone by deleting the `publicpage` table's rows.
