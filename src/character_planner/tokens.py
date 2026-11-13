"""The app's own Battle.net token, shared by everything that calls Blizzard (#107, ADR 0027).

Every call the planner makes reads public data:
- the character endpoints a sync uses (/profile/wow/character/...);
- items, recipes and talent trees.

All of them accept an app-only token from the Client Credentials grant (probed
2026-11-13: the same data as with a login). So syncs don't depend on the 24-hour
Battle.net login. Only /profile/user/wow, the account's character list, needs the user's
token, and nothing scheduled uses it.

The token is cached in StoredToken row 2 (row 1 is the login), so the API and the
worker share one. It's renewed RENEW_BEFORE its expiry, or at once after a 401. A
process lock keeps threads from fetching it twice; two processes renewing at the same
moment, about once a day, at worst fetch one spare token, which is harmless. Tokens are
never logged.
"""

import logging
import threading
import time

import httpx
from sqlmodel import Session

from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import StoredToken

logger = logging.getLogger(__name__)

APP_TOKEN_ID = 2  # StoredToken row for the app token; row 1 is the user's login
RENEW_BEFORE = 10 * 60  # seconds before expiry that a cached token is replaced

_lock = threading.Lock()


class CredentialsError(Exception):
    """Battle.net refused the app's client ID and secret, or they aren't set. Nothing that
    calls Blizzard can work until they're fixed in .env."""


def cached_app_token(session: Session) -> oauth.Token | None:
    """The stored app token while it has more than RENEW_BEFORE left, else None."""
    stored = session.get(StoredToken, APP_TOKEN_ID)
    if stored is None or stored.expires_at - time.time() <= RENEW_BEFORE:
        return None
    return oauth.Token(stored.access_token, stored.expires_at, stored.scope)


def app_token(
    session: Session,
    settings: Settings,
    http: httpx.Client | None = None,
    *,
    renew: bool = False,
) -> oauth.Token:
    """A valid app token: the cached one, or a new one from Battle.net.

    renew=True replaces the cached token even if it hasn't expired: for when Blizzard
    answered 401 to it. Raises CredentialsError when the client is missing or refused;
    other failures (network, Battle.net down) raise httpx.HTTPError as before.
    """
    if not settings.has_credentials:
        raise CredentialsError("BNET_CLIENT_ID and BNET_CLIENT_SECRET aren't set in .env")
    with _lock:
        if not renew and (cached := cached_app_token(session)) is not None:
            return cached
        try:
            token = oauth.client_credentials(settings, client=http)
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (400, 401, 403):
                raise CredentialsError(
                    "Battle.net refused the client ID and secret "
                    f"(HTTP {error.response.status_code}): check BNET_CLIENT_ID and "
                    "BNET_CLIENT_SECRET"
                ) from None
            raise
        session.merge(
            StoredToken(
                id=APP_TOKEN_ID,
                access_token=token.access_token,
                expires_at=token.expires_at,
                scope=token.scope,
            )
        )
        session.commit()
        hours = (token.expires_at - time.time()) / 3600
        logger.info("New Battle.net app token, valid for %.0f hours", hours)
        return token
