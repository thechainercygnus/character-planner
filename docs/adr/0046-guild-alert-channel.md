# 0046: The guild's alert channel: a webhook any member sets, alerts each member shares

Status: accepted (2026-11-15)

## Context

#163, #18's stretch goal: guild members' alerts in a guild Discord channel. The planner
can't tell who leads a guild: Blizzard's guild roster isn't confirmed for Forever, and
nothing in our samples shows ranks. Alerts reveal a character's progress, so sharing
must be the member's choice (ADR 0042).

## Decision

Bryce chose the three options below (2026-11-15).

1. **Any member in the guild view sets the channel.**
   - The channel is one per guild (region and guild id).
   - Any opted-in member can set, replace or remove it. Every member sees who set it and
     when.
   - Characters outside the view can't touch it (403).
   - When the last member leaves the view, or is deleted, the channel goes too. Nobody
     would be left to see or change it.
2. **It's a Discord webhook, not the bot.**
   - It needs no bot (#58), no bot in the guild's server, and no channel permissions.
   - It uses the webhook delivery from ADR 0021: retries, rate limits, and a "gone" state
     when Discord deletes the webhook.
   - It's a `guild_webhook` destination, owned by no user, so it never shows in anyone's
     Alerts settings and never gets system alerts.
   - The URL is masked, as other webhooks are.
3. **Each member ticks which of their alerts post there.**
   - Character alerts only. Nothing posts until a member ticks some.
   - After a sync, a member's ticked alerts go to the channel, while they're still in that
     guild and its view.
   - The message is the same one their own webhooks get.

## Consequences

- **Migration 0016:** `notificationdestination.guild_key` and `set_by_character_id`, and
  `guildmembership.shared_alerts`.
- **Privacy notice:** shared alerts leave the planner, to whoever can read that Discord
  channel. The notice says so.
- **Spam limits:** a member who sets a channel can point the guild's alerts anywhere a
  webhook reaches, but alerts only post for members who tick them. A member who
  mistrusts the channel unticks, or removes it.
- **Dedupe key:** an alert's key now includes the character, so two characters syncing
  in the same minute both get theirs.
