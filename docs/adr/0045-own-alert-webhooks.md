# 0045: Alert webhooks are each user's own

Status: accepted (2026-11-15). Amends ADR 0021: with users on, webhooks are no longer the
admin's alone.

## Context

ADR 0021 made alert webhooks instance-wide, and ADR 0037 kept them the admin's. With
users on (#16), every user-audience webhook got every user's character alerts, so the
admin's channel showed other users' level-ups, targets and upgrades (#164). DMs (#58,
ADR 0044) were already limited to their owner's characters.

## Decision

Bryce chose per-user webhooks (2026-11-15).

1. **Owned webhooks.** A webhook belongs to the user who adds it
   (`notificationdestination.user_id`). Each user's **Alerts** settings list, change and
   test only theirs. Anyone else's answers 404, as a DM does.
2. **Character alerts reach only the owner's webhooks and DMs.** A sync's alerts go to a
   destination only when the destination's owner owns the character. Without users,
   everything is unowned, so it all matches.
3. **System alerts are the admin's.**
   - Only the admin adds system destinations, or subscribes a webhook to system alerts.
   - With no system destination, system alerts go to the admin's own user webhooks, as
     ADR 0021's self-hosted fallback did. Never to another user's.
4. **Existing webhooks go to the admin:**
   - with migration 0015, when an admin already exists;
   - otherwise at the first sign-in, which already adopts the characters.
5. **Deleting a user deletes their webhooks** and their unsent alerts.

## Consequences

- **Alerts settings:** every signed-in user can open them. `/api/notifications` is no
  longer admin-only; the two-user route sweep lists it as the user's own.
- **Privacy notice:** it says alerts only cover the user's own characters.
