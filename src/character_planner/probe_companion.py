"""Probe the Forever Companion item API before building on it (same idea as spike.py).

Run with: uv run character-planner-probe-companion ["Item Name" ...]
Or look up item ids directly (the only cache-safe endpoint, see ADR 0004):
    uv run character-planner-probe-companion --ids 270200-270260
    uv run character-planner-probe-companion --ids 5193,2041,6460

Forever Companion (https://forevercompanion.io/developers) is a free, keyless, read-only
fan API: 120 requests/min per IP, data synced about every 6 hours. Using its data
requires linking back to it and crediting its sources (ForeverChanges, Wowhead, Zockify).

For each name: search by name, pick the exact match, then fetch the single item (which
carries tooltip lines with stat values, dropsFrom and rewardFrom). Responses go to
samples/companion-<timestamp>/.
"""

import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from character_planner import fields
from character_planner.blizzard.client import ApiResult
from character_planner.companion import BASE_URL, USER_AGENT, parse_item
from character_planner.spike import SAMPLES_DIR, save

DEFAULT_NAMES = [
    "Kindlegem Girdle",  # Hall of Thanes drop, missing from Blizzard search
    "Cape of the Brotherhood",  # Deadmines drop, missing from Blizzard search
    "Gloves of the Fang",  # Wailing Caverns drop, missing from Blizzard search
    "Dwarven Defender",  # found by Blizzard search: compare the two sources
]


def _get(
    http: httpx.Client, kind: str, path: str, params: dict[str, str] | None = None
) -> ApiResult:
    response = http.get(f"{BASE_URL}{path}", params=params)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return ApiResult(
        kind=kind, url=str(response.request.url), status=response.status_code, body=body
    )


def exact_match(body: Any, item_name: str) -> dict[str, Any] | None:
    wanted = item_name.casefold().strip()
    for item in fields.as_list(fields.get(body, "data")):
        found = fields.get(item, "name")
        if isinstance(found, str) and found.casefold().strip() == wanted and isinstance(item, dict):
            return dict(fields.as_mapping(item))
    return None


def slug(text: str) -> str:
    return text.lower().replace(" ", "-").replace("'", "")


def probe_item(http: httpx.Client, item_name: str) -> list[ApiResult]:
    results = [_get(http, f"search-{slug(item_name)}", "/items", {"q": item_name, "limit": "50"})]
    search = results[0]
    hits = fields.as_list(fields.get(search.body, "data"))
    match = exact_match(search.body, item_name) if search.ok else None

    print(f"\n{item_name}")
    print(f"  search {search.status}: {len(hits)} hits, exact match: {'yes' if match else 'no'}")
    if not match:
        names = [fields.get(h, "name") for h in hits[:8]]
        if names:
            print(f"    hits: {', '.join(str(n) for n in names)}")
        return results

    item_id = fields.get(match, "id")
    detail = _get(http, f"item-{item_id}-{slug(item_name)}", f"/items/{item_id}")
    results.append(detail)
    item = fields.get(detail.body, "data") or detail.body
    summary = {
        key: fields.get(item, key)
        for key in ("id", "itemLevel", "requiredLevel", "slot", "armor", "quality", "verified")
    }
    summary["classicOnly"] = fields.get(item, "classicOnly")
    print(f"  item {detail.status}: {summary}")
    for line in fields.as_list(fields.get(item, "tooltip")):
        right = fields.get(line, "right")
        changed = " (changed from Classic)" if fields.get(line, "changed") else ""
        text = f"{fields.get(line, 'left')}{'  |  ' + right if right else ''}"
        print(f"    tooltip: {text}{changed}")
    for drop in fields.as_list(fields.get(item, "dropsFrom")):
        print(
            f"    drops from: {fields.get(drop, 'source')} ({fields.get(drop, 'dungeon', 'name')})"
        )
    for quest in fields.as_list(fields.get(item, "rewardFrom")):
        print(f"    reward from: {fields.get(quest, 'name')} ({fields.get(quest, 'type')})")
    return results


MAX_SCAN = 120  # their limit is 120 requests per minute
SCAN_PAUSE_SECONDS = 0.55


def parse_ids(spec: str) -> list[int]:
    """'270200-270260' or '5193,2041,6460' (or a mix) into a list of ids."""
    ids: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            low, high = (int(x) for x in part.split("-", 1))
            ids.extend(range(low, high + 1))
        elif part:
            ids.append(int(part))
    return list(dict.fromkeys(ids))


def scan_ids(http: httpx.Client, ids: list[int]) -> list[ApiResult]:
    results: list[ApiResult] = []
    for index, item_id in enumerate(ids):
        if index:
            time.sleep(SCAN_PAUSE_SECONDS)
        result = _get(http, f"item-{item_id}", f"/items/{item_id}")
        if result.status == 429:
            print(f"  {item_id}: rate limited, stopping")
            break
        results.append(result)
        info = parse_item(result.body) if result.ok else None
        if info is None:
            print(f"  {item_id}: {result.status}")
            continue
        drops = f"  drops: {'; '.join(info.drops)}" if info.drops else ""
        print(
            f"  {item_id}: {info.name} | ilvl {info.item_level} | {info.slot} "
            f"| {info.armor_type} | {info.armor} armor | {info.stats}{drops}"
        )
    return results


def main() -> int:
    args = sys.argv[1:]
    with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}) as http:
        if args[:1] == ["--ids"] and len(args) == 2:
            ids = parse_ids(args[1])
            if len(ids) > MAX_SCAN:
                print(f"At most {MAX_SCAN} ids per run (got {len(ids)}).")
                return 1
            results = scan_ids(http, ids)
        else:
            names = args or DEFAULT_NAMES
            results = [result for name in names for result in probe_item(http, name)]

    out_dir = SAMPLES_DIR / f"companion-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    save(results, out_dir)
    print(f"\nSaved {len(results)} responses to {out_dir}")
    meta = fields.get(results[0].body, "meta") if results else None
    if meta:
        print(f"meta: {meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
