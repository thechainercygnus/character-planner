# 0057: Sign-ups from the app, and one-use invites

Status: accepted (2026-11-20). Amends ADR 0037: `PLANNER_SIGNUPS` becomes a default.

## Context

Sign-ups were `PLANNER_SIGNUPS`, an environment setting. Letting one person into a closed
instance meant opening sign-ups for everyone, restarting, and remembering to close them
again (#239).

## Decision

1. **The app's choice wins** (Bryce, 2026-11-18). The admin opens or closes sign-ups in the
   admin area (`signups.manage`). The choice is kept in `InstanceSetting` ("signups_open")
   and overrides `PLANNER_SIGNUPS` for good. The setting is then only the default for a new
   instance. The admin area says which one is in effect.
2. **Invites** (Bryce, 2026-11-19): a link that lets one new account sign up while sign-ups
   are closed.
   - **One use, valid for 7 days,** and revocable.
   - **The token:** 32 random bytes, stored only as its SHA-256.
   - **The link is `/#invite=<token>`.** The fragment never reaches the server, so the
     token stays out of access logs. The sign-in page posts it to `/auth/invite`, which
     checks it and holds it in an HttpOnly cookie for an hour. Battle.net's callback
     spends it and clears the cookie.
   - **An existing account signing in never spends an invite.**
   - **Who used it:** recorded as the account id, shown in the admin area.
   - **Closed invites** (used, revoked or expired) are pruned 30 days later by the
     worker's daily retention job.
3. **Logged:** opening or closing sign-ups, and making or revoking an invite, go in the
   admin action log (ADR 0056).
4. **The Discord sign-up message** (ADR 0048) follows the app's choice. A change in the
   admin area updates it in the background, and the worker uses the app's choice at
   start.

## Consequences

- **`.env` no longer has the last word:** changing `PLANNER_SIGNUPS` after the admin has
  chosen does nothing. The admin area says so.
- **`InstanceSetting` is the place for later instance-wide settings** made in the app.
  Erase keeps it (`erase.SHARED`).
- **A token can still be seen while it's in use:** whoever holds the link can use it,
  until it's used, revoked or expired.
