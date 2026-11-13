"""Probe the Forever static profession and recipe API for enchant data (issue #20).

Run with: uv run character-planner-probe-recipes

Uses an app-only (client credentials) token, so no browser login. Walks:
- /data/wow/profession/index, finding the professions below by name (not Classic ids)
- /data/wow/profession/{id}, for its skill tiers
- /data/wow/profession/{id}/skill-tier/{tier}, for recipe categories
- /data/wow/recipe/{id}, for recipes that look like enchants (names or categories below)

Response shapes are assumed from the retail API (`professions`, `skill_tiers`,
`categories[].recipes`); this probe exists to check them. Each step is tried in the plain
static namespace first, then the versioned one seen in profile hrefs.
Results go to samples/recipes-<timestamp>/.
"""

import sys
from datetime import UTC, datetime

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import ApiResult, BlizzardClient
from character_planner.config import Settings
from character_planner.enchants import PROFESSIONS, looks_like_enchant
from character_planner.probe_items import VERSIONED_NAMESPACE
from character_planner.spike import SAMPLES_DIR, save

MAX_RECIPES = 400  # all enchant categories are ~240; keeps a run under Blizzard's quotas


class Prober:
    """Gets each path from the plain namespace, falling back to the versioned one."""

    def __init__(self, client: BlizzardClient, region: str):
        self.client = client
        self.namespaces = [f"static-forever-{region}", VERSIONED_NAMESPACE.format(region=region)]
        self.results: list[ApiResult] = []

    def get(self, kind: str, path: str) -> ApiResult:
        result = self.client.get(kind, path, self.namespaces[0])
        if not result.ok:
            self.results.append(result)
            result = self.client.get(f"{kind}-versioned", path, self.namespaces[1])
        self.results.append(result)
        return result


def probe(client: BlizzardClient, region: str) -> list[ApiResult]:
    prober = Prober(client, region)
    index = prober.get("profession-index", "/data/wow/profession/index")
    wanted = {name.lower() for name in PROFESSIONS}
    professions = [
        (pid, fields.name(fields.get(p, "name")))
        for p in fields.as_list(fields.get(index.body, "professions"))
        if (pid := fields.as_int(fields.get(p, "id"))) is not None
        and (fields.name(fields.get(p, "name")) or "").lower() in wanted
    ]

    recipe_ids: list[tuple[int, str]] = []
    for pid, pname in professions:
        slug = (pname or str(pid)).lower()
        profession = prober.get(f"profession-{slug}", f"/data/wow/profession/{pid}")
        for tier in fields.as_list(fields.get(profession.body, "skill_tiers")):
            tid = fields.as_int(fields.get(tier, "id"))
            if tid is None:
                continue
            detail = prober.get(
                f"skill-tier-{slug}-{tid}", f"/data/wow/profession/{pid}/skill-tier/{tid}"
            )
            for category in fields.as_list(fields.get(detail.body, "categories")):
                cname = fields.name(fields.get(category, "name"))
                for recipe in fields.as_list(fields.get(category, "recipes")):
                    rid = fields.as_int(fields.get(recipe, "id"))
                    rname = fields.name(fields.get(recipe, "name"))
                    if rid is not None and looks_like_enchant(rname, cname):
                        recipe_ids.append((rid, slug))

    for rid, slug in recipe_ids[:MAX_RECIPES]:
        prober.get(f"recipe-{slug}-{rid}", f"/data/wow/recipe/{rid}")
    return prober.results


def main() -> int:
    settings = Settings()
    if not settings.has_credentials:
        print("Set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env first (see .env.example).")
        return 1

    token = oauth.client_credentials(settings)
    with BlizzardClient(settings, token) as client:
        results = probe(client, settings.bnet_region)

    out_dir = SAMPLES_DIR / f"recipes-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    save(results, out_dir)
    recipes = [r for r in results if r.kind.startswith("recipe-")]
    print(f"Saved {len(results)} responses to {out_dir}")
    for result in results:
        if not result.kind.startswith("recipe-"):
            print(f"  {result.status}  {result.kind}")
    ok = [r for r in recipes if r.ok]
    print(f"Recipes: {len(ok)} of {len(recipes)} fetched")
    for result in ok[:15]:
        name = fields.name(fields.get(result.body, "name"))
        description = fields.get(result.body, "description")
        print(f"  {name}: {description}")
    if len(ok) > 15:
        print(f"  ... and {len(ok) - 15} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
