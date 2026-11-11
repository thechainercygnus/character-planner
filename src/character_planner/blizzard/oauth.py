"""Battle.net OAuth 2.0: authorization code flow for the user's own profile data.

Profile endpoints for your own characters (/profile/user/wow) need a *user* token
with the wow.profile scope, which only the authorization code flow provides.
"""

import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from character_planner.config import Settings

AUTHORIZE_URL = "https://oauth.battle.net/authorize"
TOKEN_URL = "https://oauth.battle.net/token"  # noqa: S105 - a URL, not a password
SCOPE = "wow.profile"


@dataclass(frozen=True)
class Token:
    access_token: str
    expires_at: float  # unix seconds
    scope: str

    @property
    def expired(self) -> bool:
        # Treat the last minute as expired so a sync never starts with a dying token.
        return time.time() >= self.expires_at - 60


def new_state() -> str:
    """Random value tying the callback to the login that started it (CSRF guard)."""
    return secrets.token_urlsafe(32)


def authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.bnet_client_id,
        "redirect_uri": settings.bnet_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(settings: Settings, code: str, client: httpx.Client | None = None) -> Token:
    """Swap the callback's one-time code for a user access token."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.bnet_redirect_uri,
        "scope": SCOPE,
    }
    return _request_token(settings, data, client)


def client_credentials(settings: Settings, client: httpx.Client | None = None) -> Token:
    """App-only token for public game data (items, professions). No browser login."""
    return _request_token(settings, {"grant_type": "client_credentials"}, client)


def _request_token(settings: Settings, data: dict[str, str], client: httpx.Client | None) -> Token:
    own_client = client is None
    http = client or httpx.Client(timeout=15)
    try:
        response = http.post(
            TOKEN_URL,
            auth=(settings.bnet_client_id, settings.bnet_client_secret.get_secret_value()),
            data=data,
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if own_client:
            http.close()

    return Token(
        access_token=body["access_token"],
        expires_at=time.time() + int(body.get("expires_in", 0)),
        scope=body.get("scope", ""),
    )
