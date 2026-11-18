# 0049: The planner starts blank; CHARACTER_NAME is optional

Status: accepted (2026-11-17). Amends ADR 0036, point 1.

## Context

ADR 0036 made characters records, with `.env` naming the first one (`CHARACTER_NAME`,
`CHARACTER_SURNAME`, `BNET_REGION`). The backend has handled an empty name since: no
character is seeded, and every route answers with empty data. But other things made the
setting look required:
- `config.py` defaulted to Brumboldt Doomlet;
- `.env.example` set it;
- the Portainer stack refused to start without it;
- the guide said to set it.

And a blank instance was a dead end: the character switcher rendered nothing with no
characters, and the only action offered was **Sync now**, which had nothing to sync (#206).

## Decision

Bryce asked for the planner to start blank (2026-11-17).

1. **`CHARACTER_NAME` and `CHARACTER_SURNAME` default to empty.** Set, they still seed a
   first character on an empty database, as ADR 0036 says. `.env.example` comments them
   out, and the Portainer stack no longer requires them.
2. **A blank instance's front door is the add-a-character form.**
   - The landing page's "Get your character in" shows it, including the picker from the
     signed-in Battle.net account (#15), with nothing to cancel back to.
   - The header offers **Add a character**.
   - **Sync now** is hidden until there's something to sync.
3. **Messages name the app, not `.env`,** as the way to add a first character.

## Consequences

- **Existing instances are unaffected.** The settings are read only when the database has
  no characters, and theirs has one.
- **An instance that relied on the old default** (no `CHARACTER_NAME`, expecting Brumboldt
  Doomlet on an empty database) now starts blank instead. That was only ever the
  author's own character.
- **With no characters left** (all deleted), the planner is blank again, unless `.env`
  names one.
