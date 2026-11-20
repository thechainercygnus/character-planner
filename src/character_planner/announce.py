"""Announce a new version in the sign-up channel when the worker starts on it (#254).

The last version announced is kept in InstanceSetting. At start, a full release (X.Y.Z)
newer than it is posted once to DISCORD_SIGNUP_CHANNEL_ID: the version, its GitHub
release notes and the instance's address. Posted, not pinned; the pinned sign-up message
(#192) is left alone.

- The first start records the version without posting, so an existing instance doesn't
  announce one it's been running.
- A pre-release (rc or anything else not X.Y.Z) is neither posted nor recorded, so the
  full release after it still is.
- An older version (a rollback) is recorded quietly.
- A refusal is logged and the version recorded: never retried (ADR 0043, ADR 0048). Only
  an unreachable Discord leaves it for the next start.

Needs only Send Messages in the channel (`POST /channels/{id}/messages`).
"""

import logging
import re
from typing import Any, Final, Literal

import httpx
from sqlmodel import Session

from character_planner.config import Settings
from character_planner.db import InstanceSetting, utcnow
from character_planner.discord import API, bot_headers
from character_planner.notify import app_url
from character_planner.signup import POST, Refused, check

logger = logging.getLogger(__name__)

KEY: Final = "announced_version"  # the last version announced, in InstanceSetting
_RELEASE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

Outcome = Literal["off", "pre-release", "recorded", "unchanged", "posted", "refused", "unreachable"]


def release(version: str) -> tuple[int, int, int] | None:
    """A full release's numbers; None for a pre-release or anything else."""
    found = _RELEASE.fullmatch(version)
    if found is None:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


def notes_url(settings: Settings, version: str) -> str:
    """The version's GitHub release notes: release.yml makes a release per vX.Y.Z tag."""
    return f"{settings.source_url.rstrip('/')}/releases/tag/v{version}"


def message(settings: Settings, version: str) -> dict[str, Any]:
    """The post: plain text, the links in <angle brackets> so Discord adds no preview."""
    text = f"**Character Planner {version}** is out on this instance."
    address = app_url(settings)
    if address:
        text += f" Open it at <{address}>."
    text += f"\nWhat's new: <{notes_url(settings, version)}>"
    return {"content": text, "allowed_mentions": {"parse": []}}  # never a ping


def _record(session: Session, version: str) -> None:
    row = session.get(InstanceSetting, KEY) or InstanceSetting(key=KEY, value=version)
    row.value = version
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def announce(session: Session, settings: Settings, http: httpx.Client, version: str) -> Outcome:
    """Post `version` to the channel if it's a new full release; one attempt."""
    if not settings.discord_version_announcements:
        return "off"
    running = release(version)
    if running is None:
        return "pre-release"
    row = session.get(InstanceSetting, KEY)
    if row is None:
        _record(session, version)
        logger.info("Discord: recorded %s without announcing it (the first start)", version)
        return "recorded"
    last = release(row.value) if isinstance(row.value, str) else None
    if last is not None and running <= last:
        if running < last:
            _record(session, version)
        return "unchanged"
    channel = settings.discord_signup_channel_id
    try:
        check(
            http.post(
                f"{API}/channels/{channel}/messages",
                json=message(settings, version),
                headers=bot_headers(settings),
            ),
            "post in the channel",
            POST,
        )
    except Refused as refused:
        logger.warning("Discord: %s wasn't announced, and won't be retried: %s", version, refused)
        _record(session, version)
        return "refused"
    except (httpx.HTTPError, ValueError) as error:
        reason = error.__class__.__name__
        logger.warning("Discord: couldn't reach Discord to announce %s (%s)", version, reason)
        return "unreachable"
    _record(session, version)
    logger.info("Discord: announced %s", version)
    return "posted"
