"""The Professions tab's recipes (#226, ADR 0054): known, not learned yet, and their links.

Real data throughout: the professions snapshot (Mining, Engineering, Cooking, First Aid),
Engineering's skill tier from the 2026-11-12 recipe probe (trimmed to the 19 known recipes
and two others per category), and real recipe responses: Standard Scope (2435, not
known) and Soul Vessel (49656, Season of Discovery).
"""

import json
import re
from datetime import timedelta
from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs
from character_planner.config import Settings
from character_planner.crafting import refresh_crafting
from character_planner.db import BlizzardItem, CraftingRecipe, RecipeData, SkillTier, utcnow
from character_planner.leases import lease
from character_planner.recipe_book import (
    RECIPES,
    character_professions,
    recipe_book,
    refresh_recipe_book,
    tier_categories,
    wanted,
)

from .conftest import FIXTURES, tracked
from .test_app import client, mock_character_api  # noqa: F401 (the client fixture)
from .test_crafting import PROFESSIONS, store_professions
from .test_items import RECIPE, mock_battlenet

TIER = "https://us.api.blizzard.com/data/wow/profession/202/skill-tier/2941"
SEARCH = "https://www.wowhead.com/forever/search?q="


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


ENGINEERING = fixture("blizzard_skill_tier_engineering")


def store_tier(session: Session, *, age: timedelta = timedelta()) -> None:
    session.add(
        SkillTier(
            tier_id=2941,
            profession_id=202,
            profession="Engineering",
            payload=ENGINEERING,
            fetched_at=utcnow() - age,
        )
    )
    session.commit()


def store_recipe(session: Session, recipe_id: int, *, age: timedelta = timedelta()) -> None:
    session.add(
        CraftingRecipe(
            recipe_id=recipe_id,
            profession="Engineering",
            found=True,
            payload=fixture(f"blizzard_recipe_{recipe_id}"),
            fetched_at=utcnow() - age,
        )
    )
    session.commit()


def test_the_snapshot_names_each_professions_tier() -> None:
    professions = {p.name: p for p in character_professions(PROFESSIONS)}
    assert list(professions) == ["Mining", "Engineering", "Cooking", "First Aid"]
    engineering = professions["Engineering"]
    assert (engineering.profession_id, engineering.tier_id) == (202, 2941)
    assert (engineering.skill, engineering.max_skill, len(engineering.known)) == (104, 150, 19)
    assert not professions["Cooking"].primary
    assert character_professions(None) == []


def test_a_tier_lists_its_categories_in_order() -> None:
    categories = tier_categories(ENGINEERING)
    assert [name for name, _ in categories][:3] == ["Parts", "Explosives", "Ammunition"]
    sod = [(49656, "Soul Vessel"), (49864, "Polished Truesilver Gears")]
    assert ("SEASON OF DISCOVERY", sod) in categories
    assert tier_categories({"categories": [{"name": "Empty", "recipes": []}, "junk"]}) == []


def test_before_the_tier_is_cached_only_known_recipes_show(engine: Engine) -> None:
    with Session(engine) as session:
        store_professions(session)
        book = recipe_book(session, tracked(session))
    engineering = next(p for p in book.professions if p.name == "Engineering")
    assert not engineering.listed
    assert (engineering.known, engineering.unlearned) == (19, 0)
    assert [c.name for c in engineering.categories] == ["Known recipes"]
    assert all(r.known for r in engineering.categories[0].recipes)
    # Nothing fetched yet: each links to Wowhead's search for its name.
    goggles = next(r for r in engineering.categories[0].recipes if r.recipe_id == 2430)
    assert goggles.wowhead == f"{SEARCH}Flying+Tiger+Goggles"
    assert book.details_pending == 0  # nothing listed to fetch details for yet


def test_with_the_tier_cached_unlearned_recipes_are_listed_by_category(engine: Engine) -> None:
    with Session(engine) as session:
        store_professions(session)
        store_tier(session)
        store_recipe(session, 2435)  # Standard Scope: makes item 4406
        store_recipe(session, 2430)  # Flying Tiger Goggles, known: makes 4368
        book = recipe_book(session, tracked(session))

    engineering = next(p for p in book.professions if p.name == "Engineering")
    assert engineering.listed
    # 29 others in the trimmed tier, two of them Season of Discovery.
    assert (engineering.known, engineering.unlearned, engineering.season_of_discovery) == (
        19,
        27,
        2,
    )
    categories = {c.name: c for c in engineering.categories}
    assert list(categories)[:2] == ["Parts", "Explosives"]
    assert "Known recipes" not in categories and "Other known recipes" not in categories

    scopes = {r.recipe_id: r for r in categories["Scopes"].recipes}
    assert scopes[2421].known and not scopes[2435].known
    # A fetched recipe links to what it makes; one not fetched, to the search.
    assert scopes[2435].crafted_item_id == 4406
    assert scopes[2435].wowhead == "https://www.wowhead.com/forever/item=4406"
    assert scopes[2459].wowhead == f"{SEARCH}Accurate+Scope"
    goggles = next(r for r in categories["Cloth Headgear"].recipes if r.recipe_id == 2430)
    assert goggles.wowhead == "https://www.wowhead.com/forever/item=4368"

    sod = categories["SEASON OF DISCOVERY"]
    assert sod.season_of_discovery and not categories["Camping"].season_of_discovery
    # Forever's own recipes are in the tier: Reagent Bot, known, in Camping.
    assert any(r.recipe_id == 52650 and r.known for r in categories["Camping"].recipes)

    mining = next(p for p in book.professions if p.name == "Mining")
    assert not mining.listed and mining.known == 6
    # 48 listed, 2 fetched.
    assert book.details_pending == 46


def test_enchant_catalog_recipes_count_as_fetched(engine: Engine) -> None:
    with Session(engine) as session:
        store_professions(session)
        store_tier(session)
        session.add(
            RecipeData(
                recipe_id=2435,
                profession="Engineering",
                category="Scopes",
                payload=fixture("blizzard_recipe_2435"),
            )
        )
        session.commit()
        book = recipe_book(session, tracked(session))
        work = wanted(session, tracked(session))
    scope = next(
        r for p in book.professions for c in p.categories for r in c.recipes if r.recipe_id == 2435
    )
    assert scope.wowhead == "https://www.wowhead.com/forever/item=4406"
    assert 2435 not in {rid for rid, _ in work.recipes}


def test_a_known_recipe_missing_from_the_tier_is_still_shown(engine: Engine) -> None:
    with Session(engine) as session:
        store_professions(session)
        session.add(
            SkillTier(
                tier_id=2941,
                profession_id=202,
                profession="Engineering",
                payload={"categories": [{"name": "Parts", "recipes": [{"id": 1, "name": "X"}]}]},
            )
        )
        session.commit()
        book = recipe_book(session, tracked(session))
    engineering = next(p for p in book.professions if p.name == "Engineering")
    other = engineering.categories[-1]
    assert other.name == "Other known recipes" and len(other.recipes) == 19


def test_what_is_wanted_tiers_first_then_recipes(engine: Engine) -> None:
    with Session(engine) as session:
        store_professions(session)
        first = wanted(session, tracked(session))
        assert [(pid, tid) for pid, tid, _ in first.tiers] == [
            (186, 2946),
            (202, 2941),
            (185, 2939),
            (129, 2942),
        ]
        assert first.recipes == []

        store_tier(session)
        store_recipe(session, 2435)
        store_recipe(session, 2430, age=timedelta(days=22))  # past REFRESH_AFTER
        then = wanted(session, tracked(session))
        assert (202, 2941, "Engineering") not in then.tiers
        ids = {rid for rid, _ in then.recipes}
        assert 2435 not in ids and 2430 in ids and len(ids) == 47
        assert wanted(session, tracked(session), force=True).tiers[1][1] == 2941

        stale = session.get(SkillTier, 2941)
        assert stale is not None
        stale.fetched_at = utcnow() - timedelta(days=22)
        session.add(stale)
        session.commit()
        assert (202, 2941, "Engineering") in wanted(session, tracked(session)).tiers


def recipe_responder(request: httpx.Request) -> httpx.Response:
    """Standard Scope and Soul Vessel are real; one recipe fails; the rest 404."""
    rid = int(request.url.path.rsplit("/", 1)[1])
    if rid in (2435, 49656):
        return httpx.Response(200, json=fixture(f"blizzard_recipe_{rid}"))
    if rid == 2459:
        return httpx.Response(503)
    return httpx.Response(404, text="Not Found")


@respx.mock
def test_refresh_fetches_the_tier_then_its_recipes(engine: Engine, settings: Settings) -> None:
    # Routes match in the order they're added: these before mock_battlenet's recipe route.
    # A pattern of its own: respx merges a route equal to mock_battlenet's into that one.
    recipes = respx.get(url__regex=re.escape(RECIPE) + r"\d+").mock(side_effect=recipe_responder)
    tier = respx.get(url__startswith=TIER).mock(return_value=httpx.Response(200, json=ENGINEERING))
    other_tiers = respx.get(url__regex=r".*/skill-tier/\d+").mock(return_value=httpx.Response(404))
    mock_battlenet()
    with Session(engine) as session:
        store_professions(session)
        result = refresh_recipe_book(session, settings, tracked(session))
        again = refresh_recipe_book(session, settings, tracked(session))
        stored = {row.recipe_id: row.found for row in session.exec(select(CraftingRecipe))}
        book = recipe_book(session, tracked(session))

    assert tier.call_count == 1 and other_tiers.call_count == 6  # 3 others, twice: not cached
    assert result.tiers_fetched == 1
    # 48 listed: 47 stored (2 found, 45 not found), one failed and is tried again.
    assert (result.recipes_fetched, len(stored), sum(stored.values())) == (47, 47, 2)
    assert "recipe 2459: HTTP 503" in result.errors
    assert sum(e.startswith("Mining tier") for e in result.errors) == 1
    assert (again.tiers_fetched, again.recipes_fetched) == (0, 0)
    assert recipes.call_count == 49  # 48, then 2459 again
    vessel = next(
        r for p in book.professions for c in p.categories for r in c.recipes if r.recipe_id == 49656
    )
    assert vessel.wowhead == "https://www.wowhead.com/forever/item=211427"


def test_nothing_wanted_means_no_requests(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:  # no professions synced
        result = refresh_recipe_book(session, settings, tracked(session))
    assert result.model_dump() == {"tiers_fetched": 0, "recipes_fetched": 0, "errors": []}


def test_a_running_refresh_is_left_alone(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        store_professions(session)
        character_id = tracked(session)
    with lease(engine, RECIPES):
        jobs.load_recipe_book(engine, settings, character_id)  # Busy: no requests made
    with Session(engine) as session:
        assert session.exec(select(SkillTier)).first() is None


@respx.mock
def test_a_sync_loads_the_recipe_book_and_the_route_serves_it(client: TestClient) -> None:  # noqa: F811
    mock_character_api()
    mock_battlenet()
    respx.get(url__startswith=TIER).mock(return_value=httpx.Response(200, json=ENGINEERING))
    respx.get(url__regex=r".*/skill-tier/\d+").mock(return_value=httpx.Response(404))
    assert client.get("/api/recipes").json() == {"professions": [], "details_pending": 0}

    assert client.post("/api/sync").status_code == 200  # the background task runs here
    book = client.get("/api/recipes").json()
    engineering = next(p for p in book["professions"] if p["name"] == "Engineering")
    assert engineering["listed"] and engineering["unlearned"] == 27
    assert book["details_pending"] == 0  # every listed recipe was fetched (404s included)


@respx.mock
def test_crafted_gear_fetches_items_only_for_known_recipes(
    engine: Engine, settings: Settings
) -> None:
    mock_battlenet()
    with Session(engine) as session:
        store_professions(session)
        store_recipe(session, 2435)  # not known: its Standard Scope isn't the character's gear
        result = refresh_crafting(session, settings, tracked(session))
        assert session.get(BlizzardItem, 4406) is None
    assert result.items_fetched == 3  # the known recipes' items, as before
