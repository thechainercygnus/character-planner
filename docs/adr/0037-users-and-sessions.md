# 0037: Users, sessions and data ownership

Status: accepted (2026-11-14)

## Context

#16 lets more than one person use an instance, so the app has to know who is asking and
show each person only their own characters. It's also a free self-hosted tool (ADR 0020).
Someone running it for themselves shouldn't meet a sign-up step, and today the app needs
no sign-in at all (ADR 0027).

## Decision

1. **Users are off until the operator turns them on.**
   - By default (`PLANNER_USERS` unset) there are no users, no sign-in and no sessions.
     The app works exactly as before: every character belongs to the instance.
   - With `PLANNER_USERS=on`, every `/api` request needs a signed-in user, except health,
     about, status and guest mode. Without one, it answers 401.
   - The first Battle.net sign-in becomes the admin. It adopts every character that has
     no owner, so an instance moving to users keeps its data.
   - Later sign-ins are refused (403) unless the operator opens sign-ups with
     `PLANNER_SIGNUPS=on`.
2. **A user is a Battle.net account.**
   - The key is the integer `id` from `/profile/user/wow`. The existing sign-in already
     reads it with the `wow.profile` scope, and a real response shows it
     (`tests/fixtures/forever_account.json`).
   - OAuth's userinfo `sub` would need the `openid` scope and has no sample yet. The spike
     captures userinfo so the two can be compared before relying on either alone.
3. **Server-side sessions.**
   - Signing in creates a random token, sent once in a cookie: `HttpOnly`,
     `SameSite=Lax`, and `Secure` over HTTPS. Only its SHA-256 hash is stored, with an
     expiry 30 days out.
   - Logout deletes the session, so a stolen cookie stops working.
   - State-changing requests still need the app's header (#124). With `SameSite=Lax`,
     that keeps cross-site requests out.
4. **Each user's Battle.net sign-in token is their own** (`usertoken`), used only to list
   their account's characters (#15). Syncs keep using the app's own token (ADR 0027).
5. **Characters belong to a user.**
   - `character.user_id` is set when a user adds a character, or adopts one.
   - Every request resolves its character through the signed-in user. Another user's
     character, named in `X-Character-Id`, answers 404, as an unknown one does.
   - Settings belong to characters (ADR 0036), so they follow.
6. **Instance-wide settings are the admin's.** With users on, these are admin-only (403
   for others):
   - alert webhooks;
   - enchant corrections, which are shared reference data;
   - the bulk upstream refreshes (#17 takes those further).

## Consequences

- An instance without `PLANNER_USERS` changes nothing. Turning users on later hands the
  existing characters to whoever signs in first, so the operator should sign in first.
- Multi-user mode needs `BNET_REDIRECT_URI` registered on the client, as the optional
  sign-in already did.
- Account deletion, and a two-user sweep of every route, follow in #16's next step.
