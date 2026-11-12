"""Enchant catalog from Blizzard's Forever profession and recipe data (issue #20, ADR 0010).

The 2026-11-12 probe (`character-planner-probe-recipes`) showed that the static Forever API
serves every profession's skill tier, recipe categories and recipes. Enchanting recipes
carry the in-game description ("Permanently enchant bracers to give +7 Defense."), which
this module turns into stats. Items that enchant gear (scopes, armor kits, weapon stones)
are crafted items whose effect is on the item; those are listed with their crafted item
id and get effects once item data has them.

Recipes have no skill or level requirement in the API. The level an enchant comes within
reach is *estimated* from its reagents: the highest Forever Companion item level among
them (Strange Dust, Lesser Magic Essence...). Season of Discovery recipes are in the data
but excluded unless a setting includes them.
"""

import re
import time
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import CompanionInfo, as_utc, refresh_companion
from character_planner.config import Settings
from character_planner.db import RecipeData, utcnow

# Professions that put permanent or temporary enchants on gear.
PROFESSIONS = ("Enchanting", "Engineering", "Leatherworking", "Blacksmithing")
# Categories seen in the 2026-11-12 probe that hold enchants or items that enchant gear.
# Recipes elsewhere count only if their name says so (shield spikes sit in "Miscellaneous").
ENCHANT_CATEGORIES = ("enchants", "scopes", "weapon stones", "armor kits")
ENCHANT_NAMES = ("enchant ", "scope", "armor kit", "spike", "sharpening", "weightstone")
SEASON_OF_DISCOVERY = "season of discovery"
RECIPE_MAX_AGE = timedelta(days=30)  # static game data

PRIMARY_STATS = ("Strength", "Agility", "Stamina", "Intellect", "Spirit")
RESISTANCES = ("Fire", "Frost", "Nature", "Shadow", "Arcane")
WEAPON_DAMAGE = "Weapon Damage"  # flat damage per hit; scored as damage / weapon speed

# Category -> equipment slots it enchants.
CATEGORY_SLOTS: dict[str, tuple[str, ...]] = {
    "bracer enchants": ("WRIST",),
    "chest enchants": ("CHEST",),
    "cloak enchants": ("BACK",),
    "boots enchants": ("FEET",),
    "glove enchants": ("HANDS",),
    "shield enchants": ("OFF_HAND",),
    "off-hand enchants": ("OFF_HAND",),
    "weapon enchants": ("MAIN_HAND",),
    "two-handed weapon enchants": ("MAIN_HAND",),
    "amulet enchants": ("NECK",),
    "scopes": ("RANGED",),
    "weapon stones": ("MAIN_HAND",),
}
# Season of Discovery recipes sit in one category; their slot comes from the name.
NAME_SLOTS: dict[str, tuple[str, ...]] = {
    "enchant bracer": ("WRIST",),
    "enchant chest": ("CHEST",),
    "enchant cloak": ("BACK",),
    "enchant boots": ("FEET",),
    "enchant gloves": ("HANDS",),
    "enchant shield": ("OFF_HAND",),
    "enchant 2h weapon": ("MAIN_HAND",),
    "enchant weapon": ("MAIN_HAND",),
}


class Reagent(BaseModel):
    item_id: int
    name: str
    quantity: int


class EnchantOption(BaseModel):
    recipe_id: int
    name: str
    profession: str
    category: str
    slots: list[str]
    two_handed: bool = False  # 2H weapon enchants
    shield_only: bool = False  # shield enchants (not held-in-off-hand items)
    text: str | None  # the in-game description
    effects: dict[str, float]  # parsed from text; empty for procs and utility
    reagents: list[Reagent]
    crafted_item_id: int | None = None  # scopes, kits, stones: the effect is on this item
    season_of_discovery: bool = False
    estimated_level: int | None = None  # from reagent item levels; an estimate


# --- effects ---------------------------------------------------------------------------

_STAT = r"(strength|agility|stamina|intellect|spirit)"
_N = r"(\d+)"
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\+?{_N} to all stats|all stats by {_N}"), "all"),
    (re.compile(rf"\+{_N} {_STAT}\b"), "n_stat"),
    (re.compile(rf"(?:wearer's|bearer's) {_STAT} by {_N}"), "stat_n"),
    (re.compile(rf"the {_STAT} of the (?:wearer|bearer) by {_N}"), "stat_n"),
    (re.compile(rf"increase {_STAT} by {_N}"), "stat_n"),
    (re.compile(rf"(?:add|give) {_N} (?:to )?{_STAT}\b"), "n_stat"),
    (
        re.compile(rf"\+{_N} defense|defense skill of the (?:wearer|bearer) is increased by {_N}"),
        "defense",
    ),
    (re.compile(rf"{_N} additional armor|increase (?:its )?armor by {_N}"), "armor"),
    (
        re.compile(rf"to do \+?{_N} (?:additional )?(?:points? of )?damage\.|\+{_N} damage\b"),
        "damage",
    ),
    (re.compile(rf"{_N} to all resistances|resistance to all schools of magic by {_N}"), "all_res"),
    (re.compile(rf"{_N} (fire|frost|nature|shadow|arcane) resistance"), "n_res"),
    (re.compile(rf"resistance to (fire|frost|nature|shadow|arcane) by {_N}"), "res_n"),
    (re.compile(rf"\+?{_N}% chance to block"), "block"),
    (re.compile(rf"{_N}% chance to dodge"), "dodge"),
]


def _first_number(match: re.Match[str]) -> float:
    return float(next(g for g in match.groups() if g is not None and g.isdigit()))


def parse_effects(text: str | None) -> dict[str, float]:
    """Stats from an enchant description or an equipped enchant's display text.

    Procs, speed and skill bonuses have no stat to weigh and come back empty.
    """
    effects: dict[str, float] = {}
    lowered = (text or "").lower()
    for pattern, kind in _PATTERNS:
        for match in pattern.finditer(lowered):
            groups = [g for g in match.groups() if g is not None]
            if kind == "all":
                for stat in PRIMARY_STATS:
                    effects[stat] = _first_number(match)
            elif kind == "n_stat":
                effects[groups[1].title()] = float(groups[0])
            elif kind == "stat_n":
                effects[groups[0].title()] = float(groups[1])
            elif kind == "defense":
                effects["Defense"] = _first_number(match)
            elif kind == "armor":
                effects["Armor"] = _first_number(match)
            elif kind == "damage":
                effects[WEAPON_DAMAGE] = _first_number(match)
            elif kind == "all_res":
                for school in RESISTANCES:
                    effects[f"{school} Resistance"] = _first_number(match)
            elif kind == "n_res":
                effects[f"{groups[1].title()} Resistance"] = float(groups[0])
            elif kind == "res_n":
                effects[f"{groups[0].title()} Resistance"] = float(groups[1])
            elif kind == "block":
                effects["Block %"] = _first_number(match)
            elif kind == "dodge":
                effects["Dodge %"] = _first_number(match)
    return effects


# --- catalog ---------------------------------------------------------------------------


def looks_like_enchant(recipe: str | None, category: str | None) -> bool:
    cat = (category or "").lower()
    name = (recipe or "").lower()
    return any(c in cat for c in ENCHANT_CATEGORIES) or any(n in name for n in ENCHANT_NAMES)


def _slots(name: str, category: str) -> tuple[str, ...]:
    cat = category.lower()
    if cat in CATEGORY_SLOTS:
        return CATEGORY_SLOTS[cat]
    lowered = name.lower()
    # Longest prefix first: "enchant 2h weapon" before "enchant weapon".
    for prefix in sorted(NAME_SLOTS, key=len, reverse=True):
        if lowered.startswith(prefix):
            return NAME_SLOTS[prefix]
    return ()


def estimate_level(reagents: Iterable[Reagent], items: Mapping[int, CompanionInfo]) -> int | None:
    levels = [
        info.item_level
        for r in reagents
        if (info := items.get(r.item_id)) is not None and info.item_level is not None
    ]
    return max(levels, default=None)


def parse_recipe(
    payload: Any, profession: str, category: str, items: Mapping[int, CompanionInfo]
) -> EnchantOption | None:
    recipe_id = fields.as_int(fields.get(payload, "id"))
    name = fields.name(fields.get(payload, "name"))
    if recipe_id is None or not name:
        return None
    reagents = [
        Reagent(
            item_id=item_id,
            name=fields.name(fields.get(r, "reagent", "name")) or "?",
            quantity=fields.as_int(fields.get(r, "quantity")) or 1,
        )
        for r in fields.get(payload, "reagents") or []
        if (item_id := fields.as_int(fields.get(r, "reagent", "id"))) is not None
    ]
    text = fields.get(payload, "description")
    text = text.strip() if isinstance(text, str) else None
    lowered = name.lower()
    return EnchantOption(
        recipe_id=recipe_id,
        name=name,
        profession=profession,
        category=category,
        slots=list(_slots(name, category)),
        two_handed="two-handed" in category.lower() or lowered.startswith("enchant 2h"),
        shield_only="shield" in category.lower() or lowered.startswith("enchant shield"),
        text=text,
        effects=parse_effects(text),
        reagents=reagents,
        crafted_item_id=fields.as_int(fields.get(payload, "crafted_item", "id")),
        season_of_discovery=category.lower() == SEASON_OF_DISCOVERY,
        estimated_level=estimate_level(reagents, items),
    )


def catalog(
    session: Session, items: Mapping[int, CompanionInfo], *, include_sod: bool = False
) -> list[EnchantOption]:
    """Every stored enchant recipe that maps to a gear slot."""
    options = []
    for row in session.exec(select(RecipeData)).all():
        option = parse_recipe(row.payload, row.profession, row.category, items)
        if option is None or not option.slots:
            continue
        if option.season_of_discovery and not include_sod:
            continue
        options.append(option)
    return sorted(options, key=lambda o: (o.slots[0], o.name))


def reagent_and_crafted_ids(session: Session) -> list[int]:
    """Item ids worth fetching from Forever Companion: reagents (for the level estimate)
    and crafted items (where scopes, kits and stones keep their effect)."""
    ids: set[int] = set()
    for row in session.exec(select(RecipeData)).all():
        option = parse_recipe(row.payload, row.profession, row.category, {})
        if option is None:
            continue
        ids.update(r.item_id for r in option.reagents)
        if option.crafted_item_id is not None:
            ids.add(option.crafted_item_id)
    return sorted(ids)


# --- fetching --------------------------------------------------------------------------


class RecipeRefresh(BaseModel):
    professions: list[str] = []
    recipes_listed: int = 0
    recipes_fetched: int = 0
    items_fetched: int = 0  # reagents and crafted items from Forever Companion
    items_not_found: list[int] = []
    errors: list[str] = []


def refresh_recipes(
    session: Session,
    settings: Settings,
    *,
    force: bool = False,
    http: httpx.Client | None = None,
    pause: float = 0.0,
) -> RecipeRefresh:
    """Walk the professions' skill tiers and store enchant recipes not cached recently.

    Uses an app-only token. Static data, so recipes are kept for 30 days.
    """
    outcome = RecipeRefresh()
    namespace = settings.static_namespace
    cutoff = utcnow() - RECIPE_MAX_AGE
    cached = {row.recipe_id: row for row in session.exec(select(RecipeData)).all()}
    try:
        token = oauth.client_credentials(settings, client=http)
    except httpx.HTTPError as error:
        outcome.errors.append(f"Blizzard token: {error}")
        return outcome

    with BlizzardClient(settings, token, http=http) as client:
        index = client.get("profession-index", "/data/wow/profession/index", namespace)
        if not index.ok:
            outcome.errors.append(f"profession index: HTTP {index.status}")
            return outcome
        wanted = {p.lower() for p in PROFESSIONS}
        professions = [
            (pid, pname)
            for p in fields.get(index.body, "professions") or []
            if (pid := fields.as_int(fields.get(p, "id"))) is not None
            and (pname := fields.name(fields.get(p, "name"))) is not None
            and pname.lower() in wanted
        ]
        for pid, pname in professions:
            outcome.professions.append(pname)
            profession = client.get("profession", f"/data/wow/profession/{pid}", namespace)
            for tier in fields.get(profession.body, "skill_tiers") or []:
                tid = fields.as_int(fields.get(tier, "id"))
                if tid is None:
                    continue
                path = f"/data/wow/profession/{pid}/skill-tier/{tid}"
                detail = client.get("skill-tier", path, namespace)
                if not detail.ok:
                    outcome.errors.append(f"{pname} tier {tid}: HTTP {detail.status}")
                    continue
                for category in fields.get(detail.body, "categories") or []:
                    cname = fields.name(fields.get(category, "name")) or ""
                    for entry in fields.get(category, "recipes") or []:
                        rid = fields.as_int(fields.get(entry, "id"))
                        rname = fields.name(fields.get(entry, "name"))
                        if rid is None or not looks_like_enchant(rname, cname):
                            continue
                        outcome.recipes_listed += 1
                        row = cached.get(rid)
                        if row and not force and as_utc(row.fetched_at) >= cutoff:
                            continue
                        if pause:
                            time.sleep(pause)
                        recipe = client.get("recipe", f"/data/wow/recipe/{rid}", namespace)
                        if not recipe.ok:
                            outcome.errors.append(f"recipe {rid}: HTTP {recipe.status}")
                            continue
                        session.merge(
                            RecipeData(
                                recipe_id=rid,
                                profession=pname,
                                category=cname,
                                payload=recipe.body,
                                fetched_at=utcnow(),
                            )
                        )
                        outcome.recipes_fetched += 1
    session.commit()
    return outcome


def refresh_enchant_data(
    session: Session,
    settings: Settings,
    *,
    force: bool = False,
    http: httpx.Client | None = None,
) -> RecipeRefresh:
    """Recipes from Blizzard, then their reagents and crafted items from Forever Companion
    (reagent item levels give the level estimate; crafted items hold scope/kit effects)."""
    outcome = refresh_recipes(session, settings, force=force, http=http)
    items = refresh_companion(
        session,
        reagent_and_crafted_ids(session),
        force=force,
        http=http,
        max_age=RECIPE_MAX_AGE,
        pause=settings.companion_request_pause,
    )
    outcome.items_fetched = len(items.fetched)
    outcome.items_not_found = items.not_found
    outcome.errors += [f"Forever Companion {e}" for e in items.errors]
    return outcome
