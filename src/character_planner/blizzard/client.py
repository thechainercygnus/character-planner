"""Thin client for the Battle.net WoW Forever Profile API.

The Forever API is undocumented. Routes here follow community probing
(us.forums.blizzard.com threads, Nov 2026) and may change without notice, so the
client returns raw JSON and every call reports its HTTP status instead of raising:
a 404 on one endpoint is data about the API, not a crash.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from character_planner.blizzard.oauth import Token
from character_planner.config import Settings

# Character sub-resources worth probing. Keys become snapshot kinds and sample file names.
CHARACTER_ENDPOINTS: dict[str, str] = {
    "profile": "",
    "equipment": "/equipment",
    "statistics": "/statistics",
    "specializations": "/specializations",
    "professions": "/professions",
    "character-media": "/character-media",
    "appearance": "/appearance",
}


@dataclass(frozen=True)
class ApiResult:
    kind: str
    url: str
    status: int
    body: Any  # parsed JSON, or the raw text when the body is not JSON

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class BlizzardClient:
    def __init__(self, settings: Settings, token: Token, http: httpx.Client | None = None):
        self._settings = settings
        self._own_http = http is None
        self._http = http or httpx.Client(timeout=20)
        self._headers = {"Authorization": f"Bearer {token.access_token}"}

    def __enter__(self) -> BlizzardClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def get(
        self,
        kind: str,
        path: str,
        namespace: str | None = None,
        params: dict[str, str] | None = None,
    ) -> ApiResult:
        """GET any API path. Defaults to the profile namespace."""
        return self._get(kind, path, namespace, params)

    def _get(
        self,
        kind: str,
        path: str,
        namespace: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> ApiResult:
        url = f"{self._settings.api_base_url}{path}"
        params = {
            "namespace": namespace or self._settings.profile_namespace,
            "locale": "en_US",
            **(extra or {}),
        }
        response = self._http.get(url, params=params, headers=self._headers)
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return ApiResult(
            kind=kind, url=str(response.request.url), status=response.status_code, body=body
        )

    def account_profile(self) -> ApiResult:
        """Every Forever character on the logged-in account. Needs the user token."""
        return self._get("account", "/profile/user/wow")

    def character(self, kind: str) -> ApiResult:
        suffix = CHARACTER_ENDPOINTS[kind]
        return self._get(kind, f"/profile/wow/character/{self._settings.character_slug}{suffix}")

    def all_character_data(self) -> list[ApiResult]:
        return [self.character(kind) for kind in CHARACTER_ENDPOINTS]
