"""Probe the Forever static item API before building on it (same idea as spike.py).

Run with: uv run character-planner-probe-items
Or trace the name search for specific items:
    uv run character-planner-probe-items "Cape of the Brotherhood" "Tunic of Westfall"

Uses an app-only (client credentials) token, so no browser login. Tries:
- an item lookup by id in a version-free and a versioned static namespace
- the item search endpoint, by name, for a few gear targets
Results go to samples/items-<timestamp>/.
"""

import sys
from datetime import UTC, datetime

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import ApiResult, BlizzardClient
from character_planner.config import Settings
from character_planner.items import SEARCH_PATH, exact_match, search_queries
from character_planner.spike import SAMPLES_DIR, save

KNOWN_ITEM_ID = 3655  # Burnished Shield, currently equipped
# Seen in equipment hrefs on 2026-11-11; changes with game patches.
VERSIONED_NAMESPACE = "static-1.60.1_70399-forever-{region}"
SEARCH_NAMES = ["Dwarven Defender", "Kindlegem Girdle", "Flamefist Grips"]


def probe(client: BlizzardClient, region: str) -> list[ApiResult]:
    namespaces = {
        "plain": f"static-forever-{region}",
        "versioned": VERSIONED_NAMESPACE.format(region=region),
    }
    results: list[ApiResult] = []
    for label, namespace in namespaces.items():
        item_path = f"/data/wow/item/{KNOWN_ITEM_ID}"
        results.append(client.get(f"item-{KNOWN_ITEM_ID}-{label}", item_path, namespace))
        results.append(
            client.get(
                f"item-media-{KNOWN_ITEM_ID}-{label}",
                f"/data/wow/media/item/{KNOWN_ITEM_ID}",
                namespace,
            )
        )
        for name in SEARCH_NAMES:
            slug = name.lower().replace(" ", "-")
            results.append(
                client.get(
                    f"search-{slug}-{label}",
                    "/data/wow/search/item",
                    namespace,
                    {"name.en_US": name, "orderby": "id", "_page": "1"},
                )
            )
    return results


def trace_search(client: BlizzardClient, namespace: str, item_name: str) -> list[ApiResult]:
    """Page 1 of every query search_item would try, printing what each one returns."""
    results: list[ApiResult] = []
    print(f"\n{item_name}")
    for query in search_queries(item_name):
        result = client.get(
            f"trace-{query.lower().replace(' ', '-').replace("'", '')}",
            SEARCH_PATH,
            namespace,
            {"name.en_US": query, "orderby": "id", "_page": "1", "_pageSize": "100"},
        )
        results.append(result)
        body = result.body if isinstance(result.body, dict) else {}
        names = [
            f"{fields.get(r, 'data', 'id')}:{fields.name(fields.get(r, 'data', 'name'))}"
            for r in body.get("results", [])
        ]
        exact = exact_match(body, item_name)
        print(
            f"  {result.status} query={query!r} pages={body.get('pageCount')} "
            f"hits={len(names)} exact={'yes' if exact else 'no'}"
        )
        if names:
            print(f"    first: {', '.join(names[:6])}")
            print(f"    last:  {', '.join(names[-3:])}")
    return results


def main() -> int:
    settings = Settings()
    if not settings.has_credentials:
        print("Set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env first (see .env.example).")
        return 1

    names = sys.argv[1:]
    token = oauth.client_credentials(settings)
    with BlizzardClient(settings, token) as client:
        if names:
            results = [
                r for name in names for r in trace_search(client, settings.static_namespace, name)
            ]
        else:
            results = probe(client, settings.bnet_region)

    out_dir = SAMPLES_DIR / f"items-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    save(results, out_dir)
    print(f"Saved {len(results)} responses to {out_dir}:")
    for result in results:
        hits = ""
        if result.ok and isinstance(result.body, dict) and "results" in result.body:
            hits = f"  ({len(result.body['results'])} hits)"
        print(f"  {result.status}  {result.kind}{hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
