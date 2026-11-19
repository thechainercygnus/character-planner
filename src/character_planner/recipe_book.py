"""The Professions tab's recipes (#226, ADR 0054): known, and not learned yet.

Checked on 2026-11-19 against Blizzard's Forever static data (the 2026-11-12 recipe probe):

- The professions snapshot gives each profession's id, its one skill tier's id, and the
  recipes the character knows (`known_recipes`: id and name).
- GET /data/wow/profession/{id}/skill-tier/{tier} lists every recipe the profession has,
  by category: id and name only. Engineering's (2941) holds all 19 known engineering
  recipes, Forever's own included, so "not learned yet" is the tier minus the known.
- Every tier has a "SEASON OF DISCOVERY" category, which Forever players can't learn:
  flagged, and hidden by default in the tab.
- No recipe carries the skill it needs (ADR 0031), so nothing here says "learnable now".
- GET /data/wow/recipe/{id} names the `crafted_item`: the recipe's Wowhead link. Until a
  recipe is fetched, or when it makes no item, the link is Wowhead's search for its name.

Fetching is in the background after a sync (`jobs.load_recipe_book`): a profession's tier
is one call, its recipes one call each, cached as shared game data for 30 days at most.
"""

import logging
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import as_utc
from character_planner.config import Settings
from character_planner.crafting import profession_entries, profession_tier, professions_payload
from character_planner.db import CraftingRecipe, RecipeData, SkillTier, save_now, utcnow
from character_planner.enchants import SEASON_OF_DISCOVERY
from character_planner.links import item_url, search_url
from character_planner.logs import JobLog
from character_planner.retention import REFRESH_AFTER
from character_planner.tokens import CredentialsError, app_token

logger = logging.getLogger(__name__)

RECIPES: Final = "recipes"  # the lease, and its name in the status's `refreshing`
MAX_AGE: Final = REFRESH_AFTER  # refetched before the terms' 30 days (ADR 0034)
OTHER: Final = "Other known recipes"  # known, but not in the cached tier


class BookRecipe(BaseModel):
    recipe_id: int
    name: str
    known: bool
    crafted_item_id: int | None = None
    # The crafted item's page when the recipe's details are cached; else Wowhead's search.
    wowhead: str


class RecipeCategory(BaseModel):
    name: str
    season_of_discovery: bool = False
    recipes: list[BookRecipe]


class ProfessionBook(BaseModel):
    name: str
    primary: bool
    skill: int | None
    max_skill: int | None
    # The profession's skill tier is cached, so recipes not learned yet are listed. Until
    # then, only the known ones are.
    listed: bool
    known: int
    unlearned: int  # not learned yet, Season of Discovery left out
    season_of_discovery: int  # recipes in that category, learned or not
    categories: list[RecipeCategory]


class RecipeBook(BaseModel):
    professions: list[ProfessionBook]
    details_pending: int  # listed recipes whose details aren't cached yet


class Profession(BaseModel):
    """A profession of the character, as the snapshot names it."""

    name: str
    primary: bool
    profession_id: int | None
    tier_id: int | None
    skill: int | None
    max_skill: int | None
    known: dict[int, str]  # recipe id -> name


def character_professions(payload: Any) -> list[Profession]:
    out: list[Profession] = []
    for entry, primary in profession_entries(payload):
        name = fields.name(fields.get(entry, "profession", "name"))
        if not name:
            continue
        tier = profession_tier(entry)
        known: dict[int, str] = {}
        for recipe in fields.as_list(fields.get(tier, "known_recipes")):
            rid = fields.as_int(fields.get(recipe, "id"))
            rname = fields.name(fields.get(recipe, "name"))
            if rid is not None and rname:
                known[rid] = rname
        out.append(
            Profession(
                name=name,
                primary=primary,
                profession_id=fields.as_int(fields.get(entry, "profession", "id")),
                tier_id=fields.as_int(fields.get(tier, "tier", "id")),
                skill=fields.as_int(fields.get(tier, "skill_points")),
                max_skill=fields.as_int(fields.get(tier, "max_skill_points")),
                known=known,
            )
        )
    return out


def tier_categories(payload: Any) -> list[tuple[str, list[tuple[int, str]]]]:
    """A skill tier's categories: (name, [(recipe id, name)]), in the tier's order."""
    categories: list[tuple[str, list[tuple[int, str]]]] = []
    for category in fields.as_list(fields.get(payload, "categories")):
        cname = fields.name(fields.get(category, "name")) or ""
        recipes = [
            (rid, rname)
            for entry in fields.as_list(fields.get(category, "recipes"))
            if (rid := fields.as_int(fields.get(entry, "id"))) is not None
            and (rname := fields.name(fields.get(entry, "name")))
        ]
        if recipes:
            categories.append((cname, recipes))
    return categories


def is_season_of_discovery(category: str) -> bool:
    return category.strip().lower() == SEASON_OF_DISCOVERY


class RecipeDetails(BaseModel):
    """What the recipe caches know: when each recipe was fetched, and what it makes."""

    fetched: dict[int, datetime] = {}
    crafted: dict[int, int] = {}  # recipe id -> crafted item id


def recipe_details(session: Session, ids: Iterable[int]) -> RecipeDetails:
    """Both recipe caches: the crafting one (#10, and here), and the enchant catalog's."""
    wanted = list(set(ids))
    details = RecipeDetails()
    if not wanted:
        return details
    for row in session.exec(
        select(CraftingRecipe).where(col(CraftingRecipe.recipe_id).in_(wanted))
    ):
        details.fetched[row.recipe_id] = as_utc(row.fetched_at)
        item_id = fields.as_int(fields.get(row.payload, "crafted_item", "id"))
        if row.found and item_id is not None:
            details.crafted[row.recipe_id] = item_id
    for row in session.exec(select(RecipeData).where(col(RecipeData.recipe_id).in_(wanted))):
        fetched = as_utc(row.fetched_at)
        earlier = details.fetched.get(row.recipe_id)
        if earlier is None or fetched > earlier:
            details.fetched[row.recipe_id] = fetched
        item_id = fields.as_int(fields.get(row.payload, "crafted_item", "id"))
        if item_id is not None:
            details.crafted.setdefault(row.recipe_id, item_id)
    return details


def _tiers(session: Session, ids: Iterable[int | None]) -> dict[int, SkillTier]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = session.exec(select(SkillTier).where(col(SkillTier.tier_id).in_(wanted)))
    return {row.tier_id: row for row in rows}


def _recipe(rid: int, name: str, known: bool, details: RecipeDetails) -> BookRecipe:
    crafted = details.crafted.get(rid)
    return BookRecipe(
        recipe_id=rid,
        name=name,
        known=known,
        crafted_item_id=crafted,
        wowhead=item_url(crafted) or search_url(name),
    )


def recipe_book(session: Session, character_id: int | None) -> RecipeBook:
    """Each of the character's professions with its recipes, known and not learned yet."""
    professions = character_professions(professions_payload(session, character_id))
    tiers = _tiers(session, (p.tier_id for p in professions))
    listed = {
        p.name: tier_categories(tiers[p.tier_id].payload)
        for p in professions
        if p.tier_id is not None and p.tier_id in tiers
    }
    ids = [rid for p in professions for rid in p.known]
    ids += [rid for cats in listed.values() for _, recipes in cats for rid, _ in recipes]
    details = recipe_details(session, ids)

    books: list[ProfessionBook] = []
    pending = 0
    for p in professions:
        categories: list[RecipeCategory] = []
        seen: set[int] = set()
        unlearned = sod = 0
        for cname, recipes in listed.get(p.name, []):
            season = is_season_of_discovery(cname)
            rows = [_recipe(rid, name, rid in p.known, details) for rid, name in recipes]
            seen.update(r.recipe_id for r in rows)
            pending += sum(r.recipe_id not in details.fetched for r in rows)
            if season:
                sod += len(rows)
            else:
                unlearned += sum(not r.known for r in rows)
            categories.append(RecipeCategory(name=cname, season_of_discovery=season, recipes=rows))
        rest = [
            _recipe(rid, name, True, details) for rid, name in p.known.items() if rid not in seen
        ]
        if rest:
            name = OTHER if p.name in listed else "Known recipes"
            categories.append(RecipeCategory(name=name, recipes=sorted(rest, key=lambda r: r.name)))
        books.append(
            ProfessionBook(
                name=p.name,
                primary=p.primary,
                skill=p.skill,
                max_skill=p.max_skill,
                listed=p.name in listed,
                known=len(p.known),
                unlearned=unlearned,
                season_of_discovery=sod,
                categories=categories,
            )
        )
    return RecipeBook(professions=books, details_pending=pending)


# --- fetching ----------------------------------------------------------------------------


class Work(BaseModel):
    """What a character's recipe book still needs from Blizzard."""

    tiers: list[tuple[int, int, str]] = []  # (profession id, tier id, profession)
    recipes: list[tuple[int, str]] = []  # (recipe id, profession)

    def __bool__(self) -> bool:
        return bool(self.tiers or self.recipes)


def wanted(session: Session, character_id: int | None, *, force: bool = False) -> Work:
    """Tiers not cached in the last REFRESH_AFTER, then the recipes of cached tiers whose
    details aren't. A tier fetched now adds its recipes on the next call."""
    cutoff = utcnow() - MAX_AGE
    professions = character_professions(professions_payload(session, character_id))
    tiers = _tiers(session, (p.tier_id for p in professions))
    work = Work()
    for p in professions:
        if p.profession_id is None or p.tier_id is None:
            continue
        row = tiers.get(p.tier_id)
        if row is None or force or as_utc(row.fetched_at) < cutoff:
            work.tiers.append((p.profession_id, p.tier_id, p.name))
    listed = [
        (rid, p.name)
        for p in professions
        if p.tier_id in tiers
        for _, recipes in tier_categories(tiers[p.tier_id].payload)
        for rid, _ in recipes
    ]
    details = recipe_details(session, (rid for rid, _ in listed))
    seen: set[int] = set()
    for rid, profession in listed:
        fetched = details.fetched.get(rid)
        if rid in seen or (fetched is not None and not force and fetched >= cutoff):
            continue
        seen.add(rid)
        work.recipes.append((rid, profession))
    return work


class RecipeBookRefresh(BaseModel):
    tiers_fetched: int = 0
    recipes_fetched: int = 0
    errors: list[str] = []


def refresh_recipe_book(
    session: Session,
    settings: Settings,
    character_id: int | None,
    *,
    http: httpx.Client | None = None,
    force: bool = False,
    pause: float = 0.0,
) -> RecipeBookRefresh:
    """The character's professions' skill tiers, then each listed recipe's details, where
    not cached recently. Best effort: errors are returned, never raised."""
    outcome = RecipeBookRefresh()
    work = wanted(session, character_id, force=force)
    if not work:
        return outcome
    try:
        token = app_token(session, settings, http)
    except (httpx.HTTPError, CredentialsError) as error:
        outcome.errors.append(f"Blizzard token: {error}")
        return outcome
    namespace = settings.static_namespace
    with BlizzardClient(settings, token, http=http) as client:
        for pid, tid, name in work.tiers:
            path = f"/data/wow/profession/{pid}/skill-tier/{tid}"
            result = client.get("skill-tier", path, namespace)
            if not result.ok:
                outcome.errors.append(f"{name} tier {tid}: HTTP {result.status}")
                continue
            save_now(
                session,
                SkillTier(
                    tier_id=tid,
                    profession_id=pid,
                    profession=name,
                    payload=result.body,
                    fetched_at=utcnow(),
                ),
            )
            outcome.tiers_fetched += 1
        # The tiers just fetched list their recipes now.
        recipes = wanted(session, character_id, force=force).recipes
        job = JobLog(logger, "Blizzard profession recipes", len(recipes))
        for index, (rid, profession) in enumerate(recipes, start=1):
            job.step(index)
            if pause and index > 1:
                time.sleep(pause)
            result = client.get("recipe", f"/data/wow/recipe/{rid}", namespace)
            if result.status not in (200, 404):
                outcome.errors.append(f"recipe {rid}: HTTP {result.status}")
                continue
            save_now(
                session,
                CraftingRecipe(
                    recipe_id=rid,
                    profession=profession,
                    found=result.status == 200,
                    payload=result.body if result.status == 200 else None,
                    fetched_at=utcnow(),
                ),
            )
            outcome.recipes_fetched += 1
        job.done(
            f"{outcome.tiers_fetched} tiers, {outcome.recipes_fetched} recipes fetched",
            outcome.errors,
        )
    return outcome
