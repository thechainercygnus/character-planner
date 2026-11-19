# 0056: Data requests in the admin area, and the admin action log

Status: accepted (2026-11-19).

## Context

The privacy notice (#133) promises that an account can be deleted, and its data handed
over on request. Both were command-line jobs for the operator, or not possible at all.
And an operator had no record to show that a request was handled (#238).

## Decision

1. **Delete** (`users.delete`): the admin area deletes an account as
   `character-planner-db delete-user` does (`users.delete_user`). The request must carry
   the account's Battle.net id as `confirm`, and the server checks it, not just the page.
   The admin goes last (ADR 0037).
2. **Export** (`users.export`): everything stored for one account, as JSON in a zip (Bryce,
   2026-11-18). One module, `export.py`, which the account page (#217) will offer to each
   user for themselves.
   - **In it:** the account row; each character's row and its data, from the tables a
     deletion empties (`characters.OWNED`); and the alert destinations, each webhook URL
     masked.
   - **Left out:** sign-in sessions and the Battle.net token, which are secrets kept only to
     sign in, and shared game data, which is nobody's. `README.txt` says so.
3. **The action log** (`AdminAction`, read with `log.view`):
   - **What's logged:** deletions, exports, role changes and enchant corrections. Each
     entry has who, what, to which account and when, as Battle.net account ids, plus a
     short detail ("user -> superuser", "12 rows"). Never the data itself.
   - **No foreign keys:** an entry outlives the account it names, because a deletion's
     entry is the proof it happened.
   - **The command line** logs its deletions too, with no actor.
   - **Kept a year,** then pruned by the worker's daily retention job.
   - **Users on only:** without users there's no admin area, and nothing is logged.
4. **The new permissions are the admin's alone** to start. Superusers don't get them.
   Migration 0020 adds them to the admin role's row, which only keeps the row truthful:
   the admin has every permission anyway (ADR 0055).

## Consequences

- **The log is personal data:** it names Battle.net account ids, of deleted accounts too.
  The privacy notice says what it holds and for how long. A year is long enough to answer
  a question about a request, and short enough not to become a history of people.
- **Erase:** "Erase everything" (ADR 0034) empties the log with the rest, since it isn't
  in `erase.SHARED`.
- **Other permissions later:** a new permission-gated action logs itself with the same
  `log()` helper in `app.py`.
