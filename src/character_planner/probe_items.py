"""Probe the Forever static item API before building on it (same idea as spike.py).

Run with: uv run character-planner-probe-items

Uses an app-only (client credentials) token, so no browser login. Tries:
- an item lookup by id in a version-free and a versioned static namespace
- the item search endpoint, by name, for a few gear targets
Results go to samples/items-<timestamp>/.
"""

import sys
from datetime import UTC, datetime

from character_planner.blizzard import oauth
from character_planner.blizzard.client import ApiResult, BlizzardClient
from character_planner.config import Settings
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


def main() -> int:
    settings = Settings()
    if not settings.has_credentials:
        print("Set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env first (see .env.example).")
        return 1

    token = oauth.client_credentials(settings)
    with BlizzardClient(settings, token) as client:
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
