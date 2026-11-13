# 0027: Syncs use the app's own token, not the login

Status: accepted (2026-11-13). #107. Replaces ADR 0011's "a login lasts 24 hours", and
retires ADR 0021's login alerts.

## Context

- **The problem:** syncs used the Battle.net login (authorization code, `wow.profile`).
  It lasts 24 hours with no refresh token, so scheduled syncs stopped every day until
  someone logged in again. For a self-hosted planner that's the biggest everyday chore.
- **The probe (2026-11-13):** a sync only calls the character endpoints,
  `/profile/wow/character/{name-surname}/…` in `profile-forever-us`.
  - All seven return 200 to an app-only token (Client Credentials, which the item, enchant
    and talent refreshes already used), with the same fields, key path for key path, as
    the snapshots stored by logged-in syncs.
  - Only `/profile/user/wow`, the account's character list, answers 403 without the login,
    and syncs don't use it.
- **Silent re-login** (`prompt=none` and the like): not needed. It isn't documented by
  Blizzard, and would need a browser anyway.

## Decision

- **Syncs use the app token.** The worker and **Sync now** need the client ID and secret
  and the character's name, not a login.
- **One app token, `tokens.app_token`:**
  - It's shared by sync and every refresh, and cached in `StoredToken` row 2 (row 1 stays
    the login), so the API and the worker share it.
  - It's renewed 10 minutes before expiry, or at once after a 401.
  - A process lock stops threads from fetching it twice. Two processes renewing at the
    same moment, about once a day, at worst fetch one spare token. No lease: it would show
    as a refresh in the status bar, and a crash would hold it for hours.
  - Tokens are never logged.
- **Failures are told apart:**
  - a 401 from Blizzard gets one new token and one retry;
  - a second 401, or the token endpoint refusing the client (400, 401, 403), is a
    `CredentialsError`: a 503 from **Sync now**, and a failed job with its system alert in
    the worker;
  - no client at all is a quiet skip in the worker, so a guest-only instance doesn't fail
    every few hours;
  - a 404 on the profile means the character isn't found: stored, logged with what to
    check, and shown in the status bar (`/api/status` `character_found`);
  - 403, 429 and 5xx are stored and reported as before, and not retried.
- **The login stays, unused for now:** `/auth/login` and its token remain for #14's
  character list and #16's proof of ownership. The status bar and landing page no longer
  ask for it.
- **Alerts:** `login_expiring` and `login_expired` are retired. Destinations that still list
  them load and save as before; the kinds are dropped quietly.

## Consequences

- **Syncs carry on indefinitely**, as long as the client is valid.
- **Self-hosting is simpler:** no redirect URI to match. It's only needed if the login is
  used again.
- **Any character by name:** syncs can read any character, as the Armory can. On a
  single-user instance that's fine. Multi-user (#16) must still prove ownership with the
  login before attaching a character to an account.
- **If Forever ever hides a character from public lookups,** a sync would get a 404 or 403
  for it, and the user token would have to come back as a fallback for that character.
