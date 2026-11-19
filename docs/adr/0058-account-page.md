# 0058: The account page

Status: accepted (2026-11-20).

## Context

A user's own settings were spread across the app: characters in the header, alerts and
Discord in two dialogs, deletion on the Privacy page (#217). With users on, and more
characters per account, they need one place.

## Decision

1. **A page of its own** (`#account`), outside the character tabs, from **My account** in
   the ⋯ menu. The header and its character switcher stay (Bryce, 2026-11-19). It has:
   - **Characters:** each one's level, class, last sync, guild, guild view and game-data
     import, with Sync and Remove. Adding a character uses the switcher's form.
   - **Guilds:** which guilds your characters are in, and which are in the guild view.
     Joining and leaving stay on the Guild tab until #215.
   - **Alerts:** the alerts and Discord forms.
   - **Your data:** the export, and deleting the account.
   - **Sign-in:** the Battle.net account, its role, and Sign out.
2. **One form each:** the Alerts and Discord dialogs stay as header shortcuts. They and
   the page render the same form component, not copies.
3. **Deletion lives here.** Remove a character, or delete the whole account. The Privacy
   page says what's deleted and how, and links here.
4. **Self-service export:** `GET /api/account/export`, the admin area's export
   (ADR 0056) for one's own account.
5. **Without users** (a single-person instance) the page still works. It shows every
   character and no account: no sign-in section and no account deletion. The export holds
   every character and every alert destination, without `account.json`.

## Consequences

- **#215 and #216 add their per-character controls here** (guild bulk-join, build
  picker) when they ship.
- **Removing a character** is the same deletion the Privacy page had (`DELETE
  /api/character`), aimed at a row by `X-Character-Id` instead of the selected character.
- **The export is unlogged:** a user downloading their own data isn't an admin action.
