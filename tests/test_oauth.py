import time
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from character_planner.blizzard import oauth
from character_planner.config import Settings


def test_authorize_url_carries_client_scope_and_state(settings: Settings) -> None:
    url = urlparse(oauth.authorize_url(settings, "abc"))
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == oauth.AUTHORIZE_URL
    assert query["client_id"] == ["test-client"]
    assert query["scope"] == ["wow.profile"]
    assert query["state"] == ["abc"]
    assert query["redirect_uri"] == [settings.bnet_redirect_uri]


def test_new_state_is_unique() -> None:
    assert oauth.new_state() != oauth.new_state()


@respx.mock
def test_exchange_code_uses_basic_auth_and_returns_token(settings: Settings) -> None:
    route = respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 86399, "scope": "wow.profile"}
        )
    )
    token = oauth.exchange_code(settings, "the-code")

    sent = route.calls.last.request
    assert sent.headers["Authorization"].startswith("Basic ")
    assert b"code=the-code" in sent.content
    assert token.access_token == "tok"
    assert token.scope == "wow.profile"
    assert not token.expired


def test_token_counts_last_minute_as_expired() -> None:
    assert oauth.Token("t", time.time() + 30, "").expired
    assert not oauth.Token("t", time.time() + 3600, "").expired
