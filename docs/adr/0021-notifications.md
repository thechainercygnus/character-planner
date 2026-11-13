# 0021: Notifications through an outbox, to Discord webhooks

Status: accepted (2026-11-13). Stage 1 of three: bot DMs (#58) and guild channels (#18)
come later.

## Context

Scheduled syncs (ADR 0011) run unseen, and a Battle.net login lasts 24 hours with no
refresh token, so syncs stop silently. Alerts should reach people in Discord. They come
in two audiences (ADR 0020): the instance's operator, and each character's owner.

## Decision

- **Alerts:**
  - **User alerts:** login expiring (2 hours before) and expired, level-up, gear target
    reached (worn), a coming-up target now in reach (ADR 0015), and up to three new
    upgrades worth at least +3 score.
  - **System alerts:** a scheduled job failed, or a refresh hit 10 or more upstream
    errors or stopped at a rate limit.
- **Destinations** (`NotificationDestination`): a Discord webhook URL, an audience, the
  alerts it wants, and on/off.
  - User alerts go to user destinations only.
  - System alerts go to system destinations, or to user destinations while none exists,
    which is the self-hosted default.
  - `user_id` waits for #16.
- **Webhook URLs are credentials:**
  - only Discord's own webhook addresses are accepted, so a destination can't send
    requests elsewhere;
  - the API only ever returns them masked;
  - log redaction hides their token, including httpx's own request line;
  - messages disable mentions (`allowed_mentions: {parse: []}`), whatever a name contains.

  Encryption at rest is #17's.
- **Change detection:** after each sync, manual or scheduled, a digest of the character
  (level, each slot's current target and whether it's worn, the best upgrades) is compared
  with the previous one in `NotificationState`.
  - The first sync only records the baseline.
  - Nothing is built when there are no destinations.
  - No upgrades are listed without a level, because the pool isn't windowed then.
  - All of one sync's changes go out as **one message**, with a section for each change
    the destination subscribes to.
- **Outbox** (`NotificationOutbox`): alerts are queued with a dedupe key unique per
  destination, so each login warning, level and target is alerted once.
  - The worker sends what's due every pass, and a manual sync sends straight away.
  - Discord's 429 `retry_after` is respected, and stops the batch.
  - Other failures back off (1, 5, 15, 60 minutes) and give up after 5 attempts.
  - 401, 403 and 404 mark the message failed and the destination failing.
  - An alert problem never fails a sync or a job.
- **UI:** an **Alerts** dialog in the status bar, to add, switch on or off, choose alerts
  for, test and remove destinations, and to see the latest 20 alerts.

## Consequences

- Delivery needs the worker running, except for alerts from a manual sync, which are sent
  straight away. Compose runs the worker.
- The talent-point alert from #12's list is left for later.
- #58 adds a `discord_dm` kind to the same tables and outbox.
