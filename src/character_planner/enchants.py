"""Enchant catalog from Blizzard's Forever profession and recipe data (issue #20, ADR 0010).

The 2026-11-12 probe (`character-planner-probe-recipes`) showed that the static Forever API
serves every profession's skill tier, recipe categories and recipes. Enchanting recipes
carry the in-game description ("Permanently enchant bracers to give +7 Defense."), which
this module turns into stats. Items that enchant gear (scopes, armor kits, weapon stones)
are crafted items whose effect is on the item; those are listed with their crafted item
id and get effects once item data has them.

Recipes have no skill or level requirement in the API. The level an enchant comes within
reach is *estimated* from its reagents: the highest level among them, from the material
bands in data/curated/enchants.yaml (Strange Dust 1, Soul Dust 21...) or Forever
Companion's item level. Season of Discovery recipes are in the data but excluded unless
a setting includes them.

Scopes and armor kits are items whose effect no source serves; their effects come from
data/curated/enchants.yaml and from enchants seen on the character's own gear.
"""

import re
import time
from collections.abc import Iterable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import CompanionInfo, as_utc, refresh_companion
from character_planner.config import Settings
from character_planner.db import RecipeData, utcnow
from character_planner.recommend import EQUIPMENT_SLOTS, UsageRules
from character_planner.scoring import RANGED_DPS, WEAPON_DPS, Weights
from character_planner.views import EquippedItem

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
    "armor kits": ("CHEST", "LEGS", "HANDS", "FEET"),
}
# Categories whose enchants wear off (sharpening stones, weightstones).
TEMPORARY_CATEGORIES = ("weapon stones",)
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


class EnchantData(BaseModel):
    """data/curated/enchants.yaml."""

    reagent_levels: dict[int, int] = {}
    crafted_effects: dict[int, dict[str, float]] = {}
    per_slot: int = 3


def load_enchant_data(path: Path) -> EnchantData:
    with path.open(encoding="utf-8") as handle:
        return EnchantData.model_validate(yaml.safe_load(handle) or {})


EffectsSource = Literal["description", "curated", "equipped"]


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
    effects_source: EffectsSource | None = None
    temporary: bool = False  # wears off (weapon stones)
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
    (re.compile(rf"enchanted: {_STAT} \+{_N}\b"), "stat_n"),  # equipped: "Stamina +3"
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


def estimate_level(
    reagents: Iterable[Reagent],
    items: Mapping[int, CompanionInfo],
    reagent_levels: Mapping[int, int] | None = None,
) -> int | None:
    """The highest level among the reagents: curated material bands, else Forever
    Companion's item level. None when no reagent has either."""
    bands = reagent_levels or {}
    levels: list[int] = []
    for r in reagents:
        if r.item_id in bands:
            levels.append(bands[r.item_id])
        elif (info := items.get(r.item_id)) is not None and info.item_level is not None:
            levels.append(info.item_level)
    return max(levels, default=None)


def parse_recipe(
    payload: Any,
    profession: str,
    category: str,
    items: Mapping[int, CompanionInfo],
    data: EnchantData | None = None,
    equipped_effects: Mapping[int, dict[str, float]] | None = None,
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
    crafted_item_id = fields.as_int(fields.get(payload, "crafted_item", "id"))
    effects = parse_effects(text)
    source: EffectsSource | None = "description" if effects else None
    data = data or EnchantData()
    if not effects and crafted_item_id is not None:
        if crafted_item_id in (equipped_effects or {}):
            effects, source = dict((equipped_effects or {})[crafted_item_id]), "equipped"
        elif crafted_item_id in data.crafted_effects:
            effects, source = dict(data.crafted_effects[crafted_item_id]), "curated"
    return EnchantOption(
        recipe_id=recipe_id,
        name=name,
        profession=profession,
        category=category,
        slots=list(_slots(name, category)),
        two_handed="two-handed" in category.lower() or lowered.startswith("enchant 2h"),
        shield_only="shield" in category.lower() or lowered.startswith("enchant shield"),
        text=text,
        effects=effects,
        effects_source=source,
        temporary=category.lower() in TEMPORARY_CATEGORIES,
        reagents=reagents,
        crafted_item_id=crafted_item_id,
        season_of_discovery=category.lower() == SEASON_OF_DISCOVERY,
        estimated_level=estimate_level(reagents, items, data.reagent_levels),
    )


def catalog(
    session: Session,
    items: Mapping[int, CompanionInfo],
    *,
    include_sod: bool = False,
    data: EnchantData | None = None,
    equipped_effects: Mapping[int, dict[str, float]] | None = None,
) -> list[EnchantOption]:
    """Every stored enchant recipe that maps to a gear slot."""
    options = []
    for row in session.exec(select(RecipeData)).all():
        option = parse_recipe(
            row.payload, row.profession, row.category, items, data, equipped_effects
        )
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


# --- recommendations -------------------------------------------------------------------

# Ranged slots take scopes only on these weapon types.
SCOPE_WEAPONS = ("Bow", "Gun", "Crossbow")


class CurrentEnchant(BaseModel):
    text: str  # "Enchanted: Stamina +3"
    effects: dict[str, float]
    score: float


class EnchantPick(BaseModel):
    option: EnchantOption
    score: float
    score_gain: float  # over the current enchant (or none)
    usable_now: bool  # estimated level reached
    can_make: bool  # the character knows the recipe


class SlotEnchants(BaseModel):
    slot: str
    item: str | None  # equipped item name; None when the slot is empty
    current: CurrentEnchant | None
    picks: list[EnchantPick]  # biggest gain first
    current_is_weaker: bool  # an enchant on and something better in reach


class EnchantAdvice(BaseModel):
    level: int | None
    recipes: int  # catalog size; 0 means enchant data hasn't been refreshed
    rows: list[SlotEnchants]  # slots that take an enchant, in equipment order
    considered: int  # options scored for some slot
    unscored: int  # options in reach whose effect has no stat (procs, unknown items)
    unknown_level: int  # options with no level estimate, left out


def equipped_effects(equipment: Iterable[EquippedItem]) -> dict[int, dict[str, float]]:
    """Effects of enchants on the character's gear, keyed by the item that applied them
    ("Enchanted: Scope (+1 Damage)" from Crude Scope). Real game text, so it wins over
    the curated list."""
    learned: dict[int, dict[str, float]] = {}
    for item in equipment:
        for enchant in item.enchantments:
            if enchant.source_item_id is not None and (effects := parse_effects(enchant.text)):
                learned[enchant.source_item_id] = effects
    return learned


def enchant_score(
    weights: Weights, slot: str, effects: Mapping[str, float], speed: float | None
) -> float:
    """Stats x weights. Flat weapon damage counts as damage / weapon speed DPS."""
    total = 0.0
    for stat, value in effects.items():
        if stat == WEAPON_DAMAGE:
            if speed:
                total += value / speed * weights.of(RANGED_DPS if slot == "RANGED" else WEAPON_DPS)
        else:
            total += value * weights.of(stat)
    return round(total, 2)


def fits(option: EnchantOption, slot: str, worn: EquippedItem, rules: UsageRules) -> bool:
    """Whether this enchant can go on the item worn in this slot."""
    if slot not in option.slots or option.temporary:
        return False
    if option.two_handed and not rules.two_handers:
        return False
    if slot == "OFF_HAND" and option.shield_only != (worn.armor_type == "Shield"):
        return False
    return slot != "RANGED" or worn.armor_type in SCOPE_WEAPONS


def _current(
    worn: EquippedItem, slot: str, weights: Weights, crafted: Mapping[int, dict[str, float]]
) -> CurrentEnchant | None:
    permanent = [e for e in worn.enchantments if e.kind in (None, "PERMANENT")]
    if not permanent:
        return None
    enchant = permanent[0]
    effects = parse_effects(enchant.text) or dict(crafted.get(enchant.source_item_id or 0, {}))
    return CurrentEnchant(
        text=enchant.text,
        effects=effects,
        score=enchant_score(weights, slot, effects, worn.attack_speed),
    )


def advise(
    options: list[EnchantOption],
    equipped: Mapping[str, EquippedItem],
    weights: Weights,
    rules: UsageRules,
    level: int | None,
    known_recipes: set[int],
    data: EnchantData,
) -> EnchantAdvice:
    """The best enchants in reach per slot, scored against the one on now (ADR 0010)."""
    crafted = {**data.crafted_effects, **equipped_effects(equipped.values())}
    # Slots some enchant fits, plus any slot that has one on now.
    enchantable = [
        s
        for s in EQUIPMENT_SLOTS
        if any(s in o.slots for o in options) or (s in equipped and equipped[s].enchantments)
    ]
    considered: set[int] = set()
    unscored: set[int] = set()
    unknown: set[int] = set()
    rows: list[SlotEnchants] = []
    for slot in enchantable:
        worn = equipped.get(slot)
        if worn is None:
            rows.append(
                SlotEnchants(slot=slot, item=None, current=None, picks=[], current_is_weaker=False)
            )
            continue
        current = _current(worn, slot, weights, crafted)
        baseline = current.score if current else 0.0
        picks: list[EnchantPick] = []
        for option in options:
            if not fits(option, slot, worn, rules):
                continue
            can_make = option.recipe_id in known_recipes
            estimate = option.estimated_level
            # A recipe the character knows is in reach, whatever the estimate says.
            if estimate is None and not can_make:
                unknown.add(option.recipe_id)
                continue
            too_high = (
                level is not None and estimate is not None and estimate > level + rules.levels_ahead
            )
            if too_high and not can_make:
                continue
            if not option.effects:
                unscored.add(option.recipe_id)
                continue
            considered.add(option.recipe_id)
            value = enchant_score(weights, slot, option.effects, worn.attack_speed)
            if value - baseline <= 0:
                continue
            picks.append(
                EnchantPick(
                    option=option,
                    score=value,
                    score_gain=round(value - baseline, 2),
                    usable_now=can_make or level is None or estimate is None or estimate <= level,
                    can_make=can_make,
                )
            )
        picks.sort(key=lambda p: (-p.score_gain, not p.can_make, p.option.name))
        rows.append(
            SlotEnchants(
                slot=slot,
                item=worn.name,
                current=current,
                picks=picks[: data.per_slot],
                current_is_weaker=current is not None and bool(picks),
            )
        )
    return EnchantAdvice(
        level=level,
        recipes=len(options),
        rows=rows,
        considered=len(considered),
        unscored=len(unscored),
        unknown_level=len(unknown),
    )
