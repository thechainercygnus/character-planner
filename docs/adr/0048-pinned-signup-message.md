# 0048: The bot's pinned sign-up message: found among the pins, not stored

Status: accepted (2026-11-17)

Numbered 0048, not 0047: this is decided on `release/0.5` for v0.5.1, while `main` has
already used 0047 (ADR 0047, game data). The merge-back keeps both.

## Context

#192: people who find the instance's Discord server should learn what the planner is,
and how to get in, without asking. The bot from #58 can keep a pinned message saying so.
Discord's docs, read on 2026-11-17:
- **Endpoints:** `POST` and `PATCH /channels/{id}/messages`, `GET
  /channels/{id}/messages/pins`, and `PUT /channels/{id}/messages/pins/{message id}`. The
  older `/channels/{id}/pins` endpoints are deprecated.
- **Pinning has its own permission,** `PIN_MESSAGES`. `MANAGE_MESSAGES` now only covers
  deleting other users' messages.

## Decision

1. **One message per instance, in `DISCORD_SIGNUP_CHANNEL_ID`.** It's off while that's
   unset. It needs only the bot's token, not the OAuth client the DMs use.
2. **Nothing is stored.**
   - Each run lists the channel's pins, and finds the bot's own message by its author and
     a footer marker.
   - Found, it's edited to the current text. Not found (never posted, unpinned or deleted
     by hand), a new one is posted and pinned.
   - This needs no table, so no migration on `release/0.5`, whose migrations `main` has
     moved past.
3. **Its text comes from settings:**
   - the address;
   - whether users and sign-ups are on (`PLANNER_USERS`, `PLANNER_SIGNUPS`);
   - who to ask when sign-ups are closed (`OPERATOR_CONTACT`);
   - whether DMs are offered.

   Settings only change with a restart, so the worker brings the message up to date when
   it starts. The admin can also run it from the ⋯ menu, which reports Discord's answer.
4. **One attempt, never a loop (ADR 0043).**
   - Each refusal comes back to the admin, saying what to fix: a refused token, a missing
     permission (the message names all four), an unknown channel, or a rate limit.
   - If pinning is refused after posting, the bot deletes its own message, so a later
     attempt doesn't leave a second one behind. Authors may always delete their own
     messages.
5. **The permissions it needs:** View Channel, Send Messages, Read Message History and
   Pin Messages (permission integer `2251799813753856`). Not Manage Messages: Discord's
   "message pinned" notice stays.

## Consequences

- **Self-hosting:** the guide covers the channel's permissions and the setting.
- **Messages from outside:** Discord's error codes aren't on the pages read, so failures
  are told apart by HTTP status (401, 403, 404, 429). The messages shown are the
  planner's own, never Discord's text.
- **Someone else could copy the marker** into their own pinned message. It's ignored:
  only the bot's own messages count.
