"""Notifications stage 2 (#58, ADR 0044): alerts in a user's Discord DMs, from the
instance's own bot.

A user links their Discord account with Discord's OAuth (the `identify` scope, read once
for the account id and name; the OAuth token is thrown away). That makes a `discord_dm`
destination of theirs in the alert outbox (ADR 0021): only their own characters' alerts
go to it, never system alerts.

Discord's rules shape the rest (ADR 0043):
- A bot can only DM someone it shares a server with. With DISCORD_GUILD_ID set, linking
  checks the user is in it and offers DISCORD_INVITE_URL when they aren't.
- A refused DM (403, Discord's 50007 among them: DMs closed, not in the server, the bot
  blocked) pauses the destination with the reason. It isn't retried: refusals count
  toward Discord's invalid-request ban. A successful test send resumes it.
- A refused bot token (401) is the operator's problem: a system alert, and the DM waits.
- 429s wait as long as Discord says.
- At most notify.DM_DAILY_CAP DMs a day to one user, one per sync.

Discord's API is documented (https://docs.discord.com/developers/): the shapes read here
are the documented ones, read defensively.
"""

import logging
from datetime import datetime
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.config import Settings
from character_planner.db import NotificationDestination, NotificationOutbox, utcnow
from character_planner.notify import (
    ALERTS,
    COLOR,
    DM,
    DM_REFUSED,
    USER_ALERTS,
    AlertInfo,
    Message,
    NotifyError,
    SendResult,
    app_url,
    build_message,
    clean_alerts,
    deliver,
)

logger = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"  # noqa: S105 (an address)
CANNOT_MESSAGE = 50007  # Discord's "Cannot send messages to this user"
UNKNOWN_MEMBER = 10007


class DiscordError(Exception):
    """Linking failed on Discord's side (status 502)."""


# --- Discord's API --------------------------------------------------------------------------


def redirect_uri(settings: Settings) -> str:
    if settings.discord_redirect_uri:
        return settings.discord_redirect_uri
    parts = urlsplit(settings.bnet_redirect_uri)
    return f"{parts.scheme}://{parts.netloc}/auth/discord/callback"


def authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",  # no second consent screen for someone who linked before
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _bot_headers(settings: Settings) -> dict[str, str]:
    # Discord asks bots for a "DiscordBot (url, version)" User-Agent.
    return {
        "Authorization": f"Bot {settings.discord_bot_token.get_secret_value()}",
        "User-Agent": f"DiscordBot ({settings.source_url}, 1)",
    }


def _error_code(response: httpx.Response) -> int | None:
    try:
        return fields.as_int(fields.get(response.json(), "code"))
    except ValueError:
        return None


class Account(BaseModel):
    id: str
    name: str


def identify(settings: Settings, code: str, http: httpx.Client) -> Account:
    """The Discord account that approved the link. Its OAuth token is used once, here."""
    try:
        token = http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(settings),
            },
            auth=(settings.discord_client_id, settings.discord_client_secret.get_secret_value()),
            timeout=10,
        )
        if token.status_code != 200:
            raise DiscordError(f"Discord didn't accept the link ({token.status_code})")
        access = fields.get(token.json(), "access_token")
        if not isinstance(access, str) or not access:
            raise DiscordError("Discord sent no access token")
        me = http.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {access}"}, timeout=10)
        if me.status_code != 200:
            raise DiscordError(f"Discord didn't say whose account it is ({me.status_code})")
        body = me.json()
    except (httpx.HTTPError, ValueError) as error:
        raise DiscordError(f"Couldn't reach Discord ({error.__class__.__name__})") from error
    user_id = fields.get(body, "id")
    if not isinstance(user_id, str) or not user_id.isdigit():
        raise DiscordError("Discord didn't say whose account it is")
    name = fields.get(body, "global_name") or fields.get(body, "username")
    return Account(id=user_id, name=str(name)[:60] if name else "Discord")


def in_server(settings: Settings, http: httpx.Client, discord_user_id: str) -> bool | None:
    """Whether the user is in the bot's server; None when there's none set or Discord
    doesn't say (the DM then finds out)."""
    if not settings.discord_guild_id:
        return None
    try:
        response = http.get(
            f"{API}/guilds/{settings.discord_guild_id}/members/{discord_user_id}",
            headers=_bot_headers(settings),
            timeout=10,
        )
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code == 404 and _error_code(response) == UNKNOWN_MEMBER:
        return False
    logger.warning("Discord: checking server membership answered %s", response.status_code)
    return None


def _refusal(response: httpx.Response) -> SendResult:
    status = response.status_code
    if status == 429:
        retry: float | None
        try:
            retry = fields.as_float(fields.get(response.json(), "retry_after"))
        except ValueError:
            retry = None
        if retry is None:
            retry = fields.as_float(response.headers.get("retry-after")) or 5.0
        return SendResult(ok=False, status=429, error="rate limited", retry_after=retry)
    if status == 401:
        return SendResult(ok=False, status=401, error="Discord refused the bot token", bot=True)
    if status == 403:
        code = _error_code(response)
        error = "DMs refused (50007)" if code == CANNOT_MESSAGE else "HTTP 403"
        return SendResult(ok=False, status=403, error=error, gone=True)
    return SendResult(ok=False, status=status, error=f"HTTP {status}")


def send_dm(
    settings: Settings, http: httpx.Client, discord_user_id: str, message: Message
) -> SendResult:
    """Open (or reopen) the DM channel and post the message to it."""
    if not settings.discord_dms:
        return SendResult(ok=False, error="Discord DMs aren't set up on this instance", gone=True)
    headers = _bot_headers(settings)
    # A webhook's own fields (its display name) don't apply to a bot's message.
    body = {k: v for k, v in message.items() if k != "username"}
    try:
        channel = http.post(
            f"{API}/users/@me/channels",
            json={"recipient_id": discord_user_id},
            headers=headers,
            timeout=10,
        )
        if channel.status_code != 200:
            return _refusal(channel)
        channel_id = fields.get(channel.json(), "id")
        if not isinstance(channel_id, str) or not channel_id.isdigit():
            return SendResult(ok=False, status=200, error="Discord sent no DM channel")
        sent = http.post(
            f"{API}/channels/{channel_id}/messages", json=body, headers=headers, timeout=10
        )
    except (httpx.HTTPError, ValueError) as error:
        return SendResult(ok=False, error=error.__class__.__name__)
    if sent.status_code == 200:
        return SendResult(ok=True, status=200)
    return _refusal(sent)


# --- the user's link ------------------------------------------------------------------------


def linked(session: Session, user_id: int | None) -> NotificationDestination | None:
    return session.exec(
        select(NotificationDestination).where(
            NotificationDestination.kind == DM,
            col(NotificationDestination.user_id) == user_id,
        )
    ).first()


def _drop(session: Session, destination: NotificationDestination) -> None:
    for item in session.exec(
        select(NotificationOutbox).where(NotificationOutbox.destination_id == destination.id)
    ).all():
        session.delete(item)
    session.flush()
    session.delete(destination)


def link(session: Session, user_id: int | None, account: Account) -> NotificationDestination:
    """Link a Discord account: the user's one DM destination, every user alert on."""
    existing = linked(session, user_id)
    if existing is not None:
        _drop(session, existing)
    destination = NotificationDestination(
        name=account.name,
        kind=DM,
        audience="user",
        url="",
        discord_user_id=account.id,
        user_id=user_id,
        alerts=list(USER_ALERTS),
    )
    session.add(destination)
    session.commit()
    session.refresh(destination)
    logger.info("Discord: a user linked their account")
    return destination


def unlink(session: Session, user_id: int | None) -> bool:
    """Forget the linked account: its id and name, and the DMs not yet sent."""
    existing = linked(session, user_id)
    if existing is None:
        return False
    _drop(session, existing)
    session.commit()
    logger.info("Discord: a user unlinked their account")
    return True


class LinkView(BaseModel):
    name: str
    alerts: list[str]
    enabled: bool
    # Set when Discord refused a DM: the destination is paused until a test gets through.
    last_error: str | None
    last_sent_at: datetime | None


class DiscordView(BaseModel):
    available: bool  # the instance has a bot (DISCORD_* set)
    invite_url: str | None  # the bot's server, for users not in it
    linked: LinkView | None
    alerts: list[AlertInfo]  # the alerts a DM can carry: the user ones
    in_server: bool | None = None  # after linking or a test: whether they share the server


def view(
    session: Session, settings: Settings, user_id: int | None, in_server: bool | None = None
) -> DiscordView:
    destination = linked(session, user_id) if settings.discord_dms else None
    return DiscordView(
        available=settings.discord_dms,
        invite_url=settings.discord_invite_url or None,
        linked=LinkView(
            name=destination.name,
            alerts=list(destination.alerts or []),
            enabled=destination.enabled,
            last_error=destination.last_error,
            last_sent_at=destination.last_sent_at,
        )
        if destination
        else None,
        alerts=[a for a in ALERTS if a.audience == "user"],
        in_server=in_server,
    )


class LinkUpdate(BaseModel):
    alerts: list[str] | None = None
    enabled: bool | None = None


def update(session: Session, destination: NotificationDestination, change: LinkUpdate) -> None:
    if change.alerts is not None:
        destination.alerts = clean_alerts(change.alerts, "user")
        if set(destination.alerts) - set(USER_ALERTS):
            raise NotifyError("DMs only carry your own characters' alerts")
    if change.enabled is not None:
        destination.enabled = change.enabled
    session.add(destination)
    session.commit()


def send_test(
    session: Session, settings: Settings, destination: NotificationDestination, http: httpx.Client
) -> SendResult:
    """A test DM now. Getting through resumes a destination a refusal paused."""
    message = build_message(
        "Test alert from Character Planner",
        "Your alerts will arrive here. Turn them off, or unlink Discord, in the app.",
        COLOR["user"],
        app_url(settings),
    )
    result = deliver(settings, http, destination, message)
    if result.ok:
        destination.last_sent_at, destination.last_error = utcnow(), None
        destination.enabled = True
    else:
        destination.last_error = DM_REFUSED if result.gone else result.error
    session.add(destination)
    session.commit()
    return result
