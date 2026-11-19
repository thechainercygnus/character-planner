# 0062: A short status bar, and Admin without users

Status: accepted (2026-11-19).

## Context

The status bar had grown into a toolbar (#260): Sync, Alerts, Discord DMs, and a ⋯ menu
holding My account, Guest mode, Sign out, Admin, three data refreshes and the Discord
sign-up message. On a shared instance most of it isn't for most people, and instance-wide
actions sat beside personal ones. Without users there was no Admin page at all (ADR 0055,
rule 6), so a solo instance's refreshes had nowhere else to go.

## Decision (Bryce, 2026-11-19)

1. **The status bar holds** the character switcher, the last sync and **Sync now**, then
   **My account**, **Admin** and **Sign out**. No menu.
2. **Personal settings live on My account:** your alert webhooks and Discord DMs (already
   there since #217). The status bar's Alerts and Discord dialogs are gone.
3. **Instance actions live on Admin**, in a **Shared data** section: refresh item data,
   the item pool and enchants (`data.refresh`), and the Discord sign-up message
   (`discord.signup`). Each section keeps its own permission check.
4. **The Admin link shows for any admin permission**, not only `accounts.view`.
5. **Without users, Admin shows too**, with what a single person needs: shared data,
   instance health and backups. `/api/admin/health` and `/api/admin/backups` answer
   without users; the accounts, roles, sign-ups and log stay users-only (404). This
   amends ADR 0055, rule 6.
6. **Guest mode** moves to the footer.

## Consequences

- The system alert destinations stay in My account's alerts form, shown to the admin
  only. Moving them to Admin means splitting the form by audience: left for later.
- Without users, backing up now from the app writes no admin log entry, as there's no
  log without users (ADR 0056).
