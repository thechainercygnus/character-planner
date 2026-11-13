"""Item catalog: find gear-target items by name and cache their static data (ADR 0003).

The Forever item endpoint (/data/wow/item/{id}) returns 404 and Blizzard obfuscates
item stats, but item search and item media work. Search matches words, not names, so
results are filtered to the exact name. Forever-new items are often missing from the
search index; those are cached as not found and fall back to manual data in
gear_targets.yaml.
"""

from collections.abc import Iterable
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import refresh_companion
from character_planner.config import Settings
from character_planner.curated import GearTargets
from character_planner.db import CatalogItem, ItemIcon, catalog_by_name, save_now, utcnow

SEARCH_PATH = "/data/wow/search/item"
MAX_SEARCH_PAGES = 3
STOPWORDS = {"of", "the", "a", "an"}


class ItemSearchError(Exception):
    pass


class RefreshResult(BaseModel):
    found: list[str] = []
    missing: list[str] = []
    errors: list[str] = []
    icons: int = 0
    companion_fetched: int = 0
    companion_not_found: list[int] = []


def name_key(item_name: str) -> str:
    return item_name.casefold().strip()


def exact_match(body: Any, item_name: str) -> dict[str, Any] | None:
    """The search result whose name is exactly item_name (case-insensitive)."""
    wanted = name_key(item_name)
    for result in fields.get(body, "results") or []:
        data = fields.get(result, "data")
        found = fields.name(fields.get(data, "name"))
        if found and name_key(found) == wanted and isinstance(data, dict):
            return data
    return None


def search_queries(item_name: str) -> list[str]:
    """The full name, then its distinctive words, longest first.

    The search matches ANY word, so "Cape of the Brotherhood" also hits every item with
    "of" or "the" and the real item sits pages deep in id order. A single rare word
    ("Brotherhood") gives a short result list; exact_match still checks the full name.
    """
    words = [w for w in item_name.split() if w.casefold() not in STOPWORDS and len(w) > 2]
    by_length = sorted(dict.fromkeys(words), key=len, reverse=True)
    return list(dict.fromkeys([item_name, *by_length]))


def search_item(client: BlizzardClient, namespace: str, item_name: str) -> dict[str, Any] | None:
    """Find the item named exactly item_name. Raises ItemSearchError on a non-200 response."""
    for query in search_queries(item_name):
        match = _search_pages(client, namespace, query, item_name)
        if match is not None:
            return match
    return None


def _search_pages(
    client: BlizzardClient, namespace: str, query: str, item_name: str
) -> dict[str, Any] | None:
    for page in range(1, MAX_SEARCH_PAGES + 1):
        result = client.get(
            "item-search",
            SEARCH_PATH,
            namespace,
            {"name.en_US": query, "orderby": "id", "_page": str(page), "_pageSize": "100"},
        )
        if not result.ok:
            raise ItemSearchError(f"search returned HTTP {result.status}")
        match = exact_match(result.body, item_name)
        if match is not None:
            return match
        if page >= (fields.as_int(fields.get(result.body, "pageCount")) or 1):
            return None
    return None


def icon_url(body: Any) -> str | None:
    for asset in fields.get(body, "assets") or []:
        if fields.get(asset, "key") == "icon":
            value = fields.get(asset, "value")
            return value if isinstance(value, str) else None
    return None


def refresh_catalog(
    session: Session,
    settings: Settings,
    item_names: Iterable[str],
    equipped_item_ids: Iterable[int] = (),
    *,
    force: bool = False,
    http: httpx.Client | None = None,
) -> RefreshResult:
    """Look up target items and icons not cached yet (or all of them, with force)."""
    cached = catalog_by_name(session)
    known_icons = set(session.exec(select(col(ItemIcon.item_id))).all())
    names = [n for n in dict.fromkeys(item_names) if force or name_key(n) not in cached]

    outcome = RefreshResult()
    token = oauth.client_credentials(settings, client=http)
    with BlizzardClient(settings, token, http=http) as client:
        for item_name in names:
            try:
                data = search_item(client, settings.static_namespace, item_name)
            except (ItemSearchError, httpx.HTTPError) as error:
                outcome.errors.append(f"{item_name}: {error}")
                continue
            item_id = fields.as_int(fields.get(data, "id")) if data else None
            save_now(
                session,
                CatalogItem(
                    name_key=name_key(item_name),
                    name=item_name,
                    found=data is not None,
                    item_id=item_id,
                    payload=data,
                    fetched_at=utcnow(),
                ),
            )
            (outcome.found if data else outcome.missing).append(item_name)

        catalog_ids = {row.item_id for row in catalog_by_name(session).values() if row.item_id}
        wanted_icons = catalog_ids | set(equipped_item_ids)
        if not force:
            wanted_icons -= known_icons
        for item_id in sorted(wanted_icons):
            media_path = f"/data/wow/media/item/{item_id}"
            result = client.get("item-media", media_path, settings.static_namespace)
            url = icon_url(result.body) if result.ok else None
            save_now(session, ItemIcon(item_id=item_id, url=url, fetched_at=utcnow()))
            outcome.icons += url is not None

    return outcome


def refresh_item_sources(
    session: Session,
    settings: Settings,
    targets: GearTargets,
    equipped_item_ids: Iterable[int] = (),
    *,
    force: bool = False,
    http: httpx.Client | None = None,
) -> RefreshResult:
    """Blizzard item search first (for ids and icons), then Forever Companion by id.

    One source failing never stops the other; failures land in RefreshResult.errors.
    """
    try:
        outcome = refresh_catalog(
            session, settings, targets.item_names(), equipped_item_ids, force=force, http=http
        )
    except httpx.HTTPError as error:
        outcome = RefreshResult(errors=[f"Blizzard: {error}"])

    catalog_ids = [row.item_id for row in catalog_by_name(session).values() if row.item_id]
    companion = refresh_companion(
        session, [*targets.item_ids(), *catalog_ids], force=force, http=http
    )
    outcome.companion_fetched = len(companion.fetched)
    outcome.companion_not_found = companion.not_found
    outcome.errors += [f"Forever Companion {e}" for e in companion.errors]
    return outcome
