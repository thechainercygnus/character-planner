import time

import httpx
import respx

from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.config import Settings
from character_planner.probe_recipes import looks_like_enchant, probe

BASE = "https://us.api.blizzard.com/data/wow"

# Shapes assumed from the retail API; the probe exists to confirm them for Forever.
BODIES = {
    "/profession/index": {
        "professions": [{"name": "Enchanting", "id": 333}, {"name": "Herbalism", "id": 182}]
    },
    "/profession/333": {"skill_tiers": [{"name": "Enchanting", "id": 1}]},
    "/profession/333/skill-tier/1": {
        "categories": [
            {
                "name": "Bracer Enchantments",
                "recipes": [{"name": "Enchant Bracer - Minor Stamina", "id": 10}],
            },
            {"name": "Reagents", "recipes": [{"name": "Runed Copper Rod", "id": 11}]},
        ]
    },
}


def responder(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/data/wow")
    versioned = request.url.params["namespace"] != "static-forever-us"
    if path == "/recipe/10":
        # Only the versioned namespace knows the recipe: the probe must fall back.
        if versioned:
            return httpx.Response(200, json={"name": "Enchant Bracer - Minor Stamina"})
        return httpx.Response(404, text="Not Found")
    if path in BODIES:
        return httpx.Response(200, json=BODIES[path])
    return httpx.Response(404, text="Not Found")


def test_enchant_hints() -> None:
    assert looks_like_enchant("Enchant Bracer - Minor Stamina", "Bracer Enchants")
    assert looks_like_enchant("Standard Scope", "Scopes")
    assert looks_like_enchant("Coarse Sharpening Stone", "Weapon Stones")
    assert looks_like_enchant("Iron Shield Spike", "Miscellaneous")
    assert not looks_like_enchant("Runed Copper Rod", "Runed Enchanting Rods")
    assert not looks_like_enchant("Enchanted Mushroom", "SEASON OF DISCOVERY")


@respx.mock
def test_probe_walks_professions_to_enchant_recipes(settings: Settings) -> None:
    respx.get(url__startswith=BASE).mock(side_effect=responder)
    token = oauth.Token("tok", time.time() + 3600, "")
    with BlizzardClient(settings, token) as client:
        results = probe(client, "us")

    kinds = [(r.kind, r.status) for r in results]
    assert ("profession-index", 200) in kinds
    assert ("skill-tier-enchanting-1", 200) in kinds
    assert ("recipe-enchanting-10", 404) in kinds
    assert ("recipe-enchanting-10-versioned", 200) in kinds
    assert not any("herbalism" in kind for kind, _ in kinds)  # not a wanted profession
    assert not any(kind.startswith("recipe-enchanting-11") for kind, _ in kinds)  # a reagent
