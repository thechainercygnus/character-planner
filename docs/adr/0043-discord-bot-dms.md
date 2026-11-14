# 0043: Discord bot DMs: a shared server, explicit consent, and no retrying refusals

Status: accepted (2026-11-14)

## Context

#58 plans notifications stage 2: alerts sent to a user's Discord DMs by the planner's own
bot, after the user links their Discord account. Stage 1 (#12, ADR 0021) posts to
webhooks the user sets up. #96 asked three questions before #58 is built. The answers are
from Discord's documentation and policy as read on 2026-11-14.

## Findings

1. **A bot can only DM someone it shares a server with, or a friend.**
   - Discord's Create DM endpoint (`POST /users/@me/channels`) doesn't state the rule.
     Discord's guidance and the discord.js guide both give "the bot and the user do not
     share a guild" as a cause of error **50007, "Cannot send messages to this user"**.
   - The same error comes when the user has turned off DMs from server members, or has
     blocked the bot.
   - There's **no way to check beforehand**: the DM succeeds or fails with 50007.
   - **Apps added to a user's account (user-installable apps) don't change this.** They
     can respond to the user's own interactions, including in a DM with the app, but they
     don't start conversations. Discord's support article on user apps says so; its text
     wasn't readable directly (403), so this rests on the summary returned by search.
   - Sources:
     [Create DM](https://docs.discord.com/developers/resources/user),
     [application install contexts](https://docs.discord.com/developers/resources/application),
     [discord.js: common errors](https://next.discordjs.guide/guide/legacy/popular-topics/errors),
     [Using Apps on Discord](https://support.discord.com/hc/en-us/articles/21334461140375-Using-Apps-on-Discord),
     [discord-api-docs discussion #6796](https://github.com/discord/discord-api-docs/discussions/6796).
2. **The Developer Policy requires explicit permission.**
   - Its rule: "Do not contact users on Discord without their explicit permission."
     Frequent unsolicited DMs, and DMs unrelated to the app's function, are named
     violations.
   - The Create DM docs add that DMs "should generally be initiated by a user action",
     and that a bot that "open[s] a significant amount of DMs too quickly … may be rate
     limited or blocked from opening new ones".
   - Sources:
     [Discord Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy),
     effective 2024-07-08, as quoted by search because the page refuses automated reads;
     [Create DM](https://docs.discord.com/developers/resources/user).
3. **Rate limits:**
   - **50 requests a second per bot**, plus per-route limits announced in the
     `X-RateLimit-*` headers.
   - A **429** carries `Retry-After`, and `X-RateLimit-Scope` says whether the limit is the
     user's, global or shared.
   - **10,000 invalid requests** (401, 403 and 429, apart from shared-scope 429s) in 10
     minutes get the IP temporarily banned by Cloudflare.
   - No DM-specific number is published.
   - Source: [Rate limits](https://docs.discord.com/developers/topics/rate-limits).

## Decision, for #58

1. **The bot lives in a server its users are in.**
   - **A self-hosted instance** creates its own Discord application and bot (token in
     `.env`) and adds the bot to a server its users share: the operator's, or the guild's
     (#18). That server is also where #18's guild-channel alerts would post.
   - **The managed instance** (ADR 0020) runs one bot in a Character Planner community
     server that users join to get DMs.
   - Linking a Discord account checks that the user shares that server with the bot. If
     not, the user is told how to join, not left to fail silently.
2. **Explicit consent, per alert kind.**
   - The user links their Discord account through Discord's OAuth (the `identify` scope,
     for the user id only), then turns on each alert kind they want.
   - The bot sends nothing a user hasn't turned on, and nothing but those alerts: no
     announcements, no promotion.
   - Unlinking, or turning an alert off, stops it at once.
3. **Few DMs, triggered by the user's own syncs.**
   - At most one DM per sync, the digest #12 already builds, and a daily cap per user.
   - Never a broadcast to a server's members.
   - DMs go out one at a time from the worker's existing outbox (ADR 0021).
4. **A refusal isn't retried.**
   - **50007 or another 403:** the user's DM destination is marked unreachable, the app
     says why (DMs from server members off, not in the server, or the bot blocked), and it
     stays paused until the user fixes it and tests it. That spares the invalid-request
     budget.
   - **429:** honour `Retry-After` and `X-RateLimit-Scope`.
   - **401:** the bot token is wrong, so it's a system alert to the operator, and sending
     stops.
5. **Webhooks stay.** Stage 1's webhooks need no bot and no shared server. They remain
   the simple path, and the only one on an instance without a bot.

## Consequences

- **#58 can be built on this:** Discord OAuth linking with `identify`, a check that the
  user shares the server, a consent toggle per alert kind, outbox delivery with the
  refusal and rate-limit rules above, and an in-app "unreachable" state with the reason.
- **Operators need more setup:** a Discord application and a server for the bot. The
  self-hosting guide will say so when #58 lands.
- **The shared-server rule rests on Discord's guidance and observed behaviour, not on the
  API reference.** #58's tests should treat 50007 as a normal outcome.
