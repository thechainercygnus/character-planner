"""The bot's pinned sign-up message (#192, ADR 0048).

With DISCORD_SIGNUP_CHANNEL_ID set, the instance's bot keeps one pinned message in that
channel: what the planner is, where it is, and whether sign-ups are open. `ensure` finds
the bot's own pinned message (its author, and the marker in its footer) and edits it to
the current text, or posts and pins a new one. Nothing is stored: the pins are the record.

Discord's rules (ADR 0043) shape the failures: a refusal (missing permissions, an unknown
channel, a refused token) is reported to the admin once and never retried, since refusals
count toward Discord's invalid-request limit.

Endpoints and permissions are from Discord's docs (checked 2026-11-17, on #192):
- `POST /channels/{id}/messages` (SEND_MESSAGES), `PATCH .../messages/{id}` (the author);
- `GET /channels/{id}/messages/pins` (VIEW_CHANNEL and READ_MESSAGE_HISTORY), answering
  `{"items": [{"pinned_at": ..., "message": {...}}], "has_more": ...}`;
- `PUT /channels/{id}/messages/pins/{message id}` (PIN_MESSAGES).
"""

import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from character_planner import fields
from character_planner.config import Settings
from character_planner.discord import API, bot_headers
from character_planner.notify import app_url

logger = logging.getLogger(__name__)

MARKER = "Character Planner · sign-up"  # the footer that marks the bot's own message
PERMISSIONS = "View Channel, Send Messages, Read Message History and Pin Messages"


class Outcome(BaseModel):
    """What happened, for the admin."""

    ok: bool
    action: Literal["posted", "updated", "none"]
    message_id: str | None = None
    error: str | None = None


def message(settings: Settings) -> dict[str, Any]:
    """The message as it should read now."""
    address = app_url(settings)
    lines = [
        "Plan your WoW Forever character: the gear upgrades in reach, the dungeons worth "
        "running, enchants, and how your talents compare with your plan.",
        "",
    ]
    if address:
        lines.append(f"**Open it:** {address} and sign in with Battle.net.")
    if not settings.planner_users:
        lines.append("It's a single-person instance: there's nothing to sign up for.")
    elif settings.planner_signups:
        lines.append("**Sign-ups are open:** your first sign-in creates your account.")
    else:
        contact = settings.operator_contact
        lines.append(
            "**Sign-ups are closed** for now."
            + (f" Ask {contact} to be let in." if contact else " Ask whoever runs it.")
        )
    if settings.discord_dms:
        lines.append(
            "**Alerts as DMs:** once signed in, open **Discord** in the planner to link "
            "your account and choose your alerts."
        )
    return {
        "embeds": [
            {
                "title": "Character Planner",
                "description": "\n".join(lines),
                "color": 0xE0B04A,
                "footer": {"text": MARKER},
            }
        ],
        # Never a ping, whatever the text holds.
        "allowed_mentions": {"parse": []},
    }


class _Refused(Exception):
    """Discord said no: the message is the admin's to read."""


def _check(response: httpx.Response, doing: str) -> Any:
    if response.status_code in (200, 201, 204):
        return response.json() if response.content else None
    if response.status_code == 401:
        raise _Refused("Discord refused DISCORD_BOT_TOKEN")
    if response.status_code == 403:
        raise _Refused(f"The bot isn't allowed to {doing}: give it {PERMISSIONS} in that channel")
    if response.status_code == 404:
        raise _Refused(
            "Discord doesn't know DISCORD_SIGNUP_CHANNEL_ID, or the bot can't see it: "
            "check the id, and that the bot is in that server"
        )
    if response.status_code == 429:
        raise _Refused("Discord is rate limiting the bot: try again in a few minutes")
    raise _Refused(f"Discord answered {response.status_code} when trying to {doing}")


def _ours(pins: Any, bot_id: str) -> str | None:
    """The id of the bot's own pinned sign-up message, if it's still pinned."""
    for pin in fields.as_list(fields.get(pins, "items")):
        found = fields.get(pin, "message")
        author = fields.get(found, "author", "id")
        embeds = fields.as_list(fields.get(found, "embeds"))
        marked = any(fields.get(e, "footer", "text") == MARKER for e in embeds)
        message_id = fields.get(found, "id")
        if author == bot_id and marked and isinstance(message_id, str):
            return message_id
    return None


def ensure(settings: Settings, http: httpx.Client) -> Outcome:
    """Make the channel's pinned sign-up message current: edit the bot's own, or post and
    pin a new one. One attempt; a refusal comes back as the outcome, never retried."""
    if not settings.discord_signup_message:
        return Outcome(ok=False, action="none", error="DISCORD_SIGNUP_CHANNEL_ID isn't set")
    channel = settings.discord_signup_channel_id
    headers = bot_headers(settings)
    body = message(settings)
    try:
        me = _check(http.get(f"{API}/users/@me", headers=headers), "read its own account")
        bot_id = fields.get(me, "id")
        pins = _check(
            http.get(f"{API}/channels/{channel}/messages/pins", headers=headers),
            "read the channel's pins",
        )
        existing = _ours(pins, bot_id) if isinstance(bot_id, str) else None
        if existing is not None:
            _check(
                http.patch(
                    f"{API}/channels/{channel}/messages/{existing}", json=body, headers=headers
                ),
                "edit its message",
            )
            logger.info("Discord: the sign-up message is up to date")
            return Outcome(ok=True, action="updated", message_id=existing)
        posted = _check(
            http.post(f"{API}/channels/{channel}/messages", json=body, headers=headers),
            "post in the channel",
        )
        message_id = fields.get(posted, "id")
        if not isinstance(message_id, str):
            raise _Refused("Discord didn't say which message it posted")
        pinned = http.put(f"{API}/channels/{channel}/messages/pins/{message_id}", headers=headers)
        try:
            _check(pinned, "pin its message")
        except _Refused:
            # Unpinned, the next attempt wouldn't find it and would post another: take it
            # back (authors may always delete their own messages), then report.
            http.delete(f"{API}/channels/{channel}/messages/{message_id}", headers=headers)
            raise
    except _Refused as refused:
        logger.warning("Discord: the sign-up message wasn't updated: %s", refused)
        return Outcome(ok=False, action="none", error=str(refused))
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Discord: couldn't reach Discord (%s)", error.__class__.__name__)
        return Outcome(ok=False, action="none", error="Couldn't reach Discord: try again")
    logger.info("Discord: posted and pinned the sign-up message")
    return Outcome(ok=True, action="posted", message_id=message_id)
