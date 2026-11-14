# 0044: Discord DMs: one linked account per user, in the alert outbox

Status: accepted (2026-11-14)

## Context

#58 sends a user's alerts as private messages from the instance's own bot. ADR 0043 sets
Discord's constraints: a shared server, explicit consent, few DMs, and refusals that
aren't retried. This records how the planner meets them.

## Decision

1. **On only with a bot.**
   - `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` all set turn
     it on. Without them, `/api/discord` says it's unavailable and the Discord button
     isn't shown.
   - `DISCORD_GUILD_ID` names the bot's server and `DISCORD_INVITE_URL` invites people to
     it. Both are optional.
2. **Linking keeps only the id and name.**
   - Discord's OAuth asks for `identify`. The planner reads the account's id and name
     once; its token isn't kept.
   - The OAuth state is tied to the signed-in user, so no other browser can finish it.
   - A user has one linked account; linking again replaces it.
   - Unlinking deletes the id, the name and any unsent DMs. So does deleting the user.
3. **A DM destination in the existing outbox (ADR 0021).**
   - A `discord_dm` row in `notificationdestination`, owned by the user (`user_id`), with
     the Discord id and no URL.
   - It gets the alerts of its owner's own characters only: never system alerts, never
     another user's characters.
   - It's capped at 12 a day (`DM_DAILY_CAP`), one digest per sync at most.
   - The admin's Alerts settings list webhooks only. Users' DMs are theirs.
4. **Sending:** open the DM channel (`POST /users/@me/channels`), then post the message.
   A webhook's `username` field is dropped, and mentions stay off.
5. **Refusals:**
   - **403** (50007 or another): the DM is dropped, and the destination is paused with
     the reason. It isn't retried. A test DM that gets through resumes it.
   - **429:** wait `retry_after`. The rest of the queue waits too.
   - **401:** the bot token is wrong. The DM waits an hour, the operator gets a system
     alert, and the user's destination isn't touched.
6. **Test DMs** also ask Discord whether the user is in the bot's server
   (`GET /guilds/{id}/members/{user}`), so the app can show the invite when they aren't.

## Consequences

- **Migration 0014:** adds `notificationdestination.discord_user_id`.
- **Privacy:** the privacy notice lists the linked account's id and name.
- **Webhooks:** user-audience webhooks still get every character's alerts. With users on,
  that's every user's. They stay the admin's, as ADR 0021 set.
- **Guild-channel alerts** (#18's stretch) can reuse the bot and the server. They're
  still to come.
