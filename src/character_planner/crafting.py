"""Professions: rank milestones and crafted gear (#10, ADR 0031).

Checked on 2026-11-13 against Blizzard's Forever static data:

- The professions snapshot lists each profession's skill, its cap and the recipes the
  character knows (`known_recipes`: id and name).
- GET /data/wow/recipe/{id} names the `crafted_item`. A recipe carries no skill needed
  to craft it, and each profession has a single skill tier, so recipes not yet learned
  can't be placed by skill. A known recipe can be crafted, so those are the candidates.
- GET /data/wow/item/{id} has the crafted item's stats, armor, weapon damage, required
  level and item level under `preview_item`, in the shape equipped items use. Forever
  Companion doesn't list crafted items (404), so these are their item details.

Trainer ranks aren't in either API: data/curated/professions.yaml holds Classic's.
"""

import logging
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.blizzard.client import BlizzardClient
from character_planner.companion import CompanionInfo, as_utc
from character_planner.config import Settings
from character_planner.db import BlizzardItem, CraftingRecipe, latest_by_kind, save_now, utcnow
from character_planner.logs import JobLog
from character_planner.retention import REFRESH_AFTER
from character_planner.tokens import CredentialsError, app_token

logger = logging.getLogger(__name__)

# Refreshed before the terms' 30 days (#131, ADR 0034).
CRAFTING_MAX_AGE = REFRESH_AFTER
# Inventory types that are equippable but not gear: Crafted Heavy Shot is "AMMO".
NOT_GEAR = ("AMMO",)


class Rank(BaseModel):
    name: str
    max_skill: int
    train_at_skill: int
    train_at_level: int


class ProfessionData(BaseModel):
    """data/curated/professions.yaml."""

    ranks: list[Rank]
    notes: dict[str, str] = {}


class KnownRecipe(BaseModel):
    recipe_id: int
    name: str
    profession: str


class CraftedItem(BaseModel):
    """An equippable item the character can craft now, with its details."""

    item_id: int
    name: str
    profession: str
    recipe: str
    info: CompanionInfo  # the same item details the pool scores, from Blizzard


class NextRank(BaseModel):
    name: str
    max_skill: int
    train_at_skill: int
    train_at_level: int
    skill_ready: bool  # skill reached
    level_ready: bool  # character level reached


class ProfessionRow(BaseModel):
    name: str
    primary: bool
    skill: int | None
    max_skill: int | None
    rank: str | None  # from the cap: Journeyman for 150
    next_rank: NextRank | None  # None at the last rank, or with no data
    note: str | None = None  # how a rank is earned when it isn't a trainer
    known_recipes: int
    crafted_gear: list[str]  # equippable items its known recipes make


class ProfessionsView(BaseModel):
    level: int | None
    professions: list[ProfessionRow]


def load_profession_data(path: Path) -> ProfessionData:
    return ProfessionData.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _professions(payload: Any) -> list[tuple[Mapping[str, Any], bool]]:
    """(profession entry, primary?) from a professions snapshot."""
    entries: list[tuple[Mapping[str, Any], bool]] = []
    for key, primary in (("primaries", True), ("secondaries", False)):
        for entry in fields.as_list(fields.get(payload, key)):
            if isinstance(entry, Mapping):
                entries.append((fields.as_mapping(entry), primary))
    return entries


def _tier(entry: Any) -> Any:
    """A profession's skill tier: Forever's professions have one each."""
    tiers = fields.as_list(fields.get(entry, "tiers"))
    return tiers[0] if tiers else None


def known_recipes(payload: Any) -> list[KnownRecipe]:
    """Every recipe the character knows, from a professions snapshot."""
    recipes: list[KnownRecipe] = []
    for entry, _ in _professions(payload):
        profession = fields.name(fields.get(entry, "profession", "name"))
        for recipe in fields.as_list(fields.get(_tier(entry), "known_recipes")):
            rid = fields.as_int(fields.get(recipe, "id"))
            name = fields.name(fields.get(recipe, "name"))
            if rid is not None and name and profession:
                recipes.append(KnownRecipe(recipe_id=rid, name=name, profession=profession))
    return recipes


def item_info(payload: Any) -> CompanionInfo | None:
    """A Blizzard item as pool item details; None for an item that can't be equipped, or
    is ammunition (equippable to Blizzard, but no slot the planner scores)."""
    item_id = fields.as_int(fields.get(payload, "id"))
    if item_id is None or fields.get(payload, "is_equippable") is not True:
        return None
    if fields.get(payload, "inventory_type", "type") in NOT_GEAR:
        return None
    preview = fields.get(payload, "preview_item")
    item_class = fields.get(payload, "item_class", "name")
    subclass = fields.name(fields.get(payload, "item_subclass", "name"))
    is_weapon = item_class == "Weapon"
    is_shield = item_class == "Armor" and subclass == "Shield"
    required = fields.as_int(fields.get(payload, "required_level"))
    stats = {
        name: value
        for stat in fields.as_list(fields.get(preview, "stats"))
        if (name := fields.name(fields.get(stat, "type", "name"))) is not None
        and (value := fields.as_int(fields.get(stat, "value"))) is not None
    }
    dps = fields.get(preview, "weapon", "dps", "value")
    quality = fields.get(payload, "quality", "type")
    return CompanionInfo(
        item_id=item_id,
        name=fields.name(fields.get(payload, "name")),
        item_level=fields.as_int(fields.get(payload, "level")),
        required_level=required or None,  # 0 means none
        quality=quality if isinstance(quality, str) else None,
        slot=fields.name(fields.get(payload, "inventory_type", "name")),
        weapon_type=subclass if is_weapon or is_shield else None,
        armor_type=subclass if item_class == "Armor" and not is_shield else None,
        armor=fields.as_int(fields.get(preview, "armor", "value")),
        stats=stats,
        dps=round(dps, 1) if isinstance(dps, int | float) else None,
        wowhead=f"https://www.wowhead.com/forever/item={item_id}",
    )


def _crafted_ids(session: Session) -> dict[int, int]:
    """recipe id -> crafted item id, for stored recipes."""
    out: dict[int, int] = {}
    for row in session.exec(select(CraftingRecipe)).all():
        item_id = fields.as_int(fields.get(row.payload, "crafted_item", "id"))
        if row.found and item_id is not None:
            out[row.recipe_id] = item_id
    return out


def _professions_payload(session: Session) -> Any:
    snapshot = latest_by_kind(session).get("professions")
    return snapshot.payload if snapshot else None


def crafted_items(session: Session) -> list[CraftedItem]:
    """Equippable items from the recipes the synced character knows."""
    crafted_ids = _crafted_ids(session)
    items = {
        row.item_id: row.payload for row in session.exec(select(BlizzardItem)).all() if row.found
    }
    out: dict[int, CraftedItem] = {}
    for recipe in known_recipes(_professions_payload(session)):
        item_id = crafted_ids.get(recipe.recipe_id)
        info = item_info(items.get(item_id)) if item_id is not None else None
        if item_id is None or info is None or item_id in out:
            continue
        out[item_id] = CraftedItem(
            item_id=item_id,
            name=info.name or recipe.name,
            profession=recipe.profession,
            recipe=recipe.name,
            info=info,
        )
    return sorted(out.values(), key=lambda c: (c.profession, c.name))


def _rank_for(cap: int | None, ranks: list[Rank]) -> tuple[Rank | None, Rank | None]:
    """The rank a skill cap means, and the next one."""
    if cap is None:
        return None, None
    current = next((r for r in ranks if r.max_skill == cap), None)
    later = [r for r in ranks if r.max_skill > cap]
    return current, (later[0] if later else None)


def professions_view(session: Session, data: ProfessionData, level: int | None) -> ProfessionsView:
    """Each synced profession: skill against its cap, the rank and the next one."""
    ranks = sorted(data.ranks, key=lambda r: r.max_skill)
    gear: dict[str, list[str]] = {}
    for item in crafted_items(session):
        gear.setdefault(item.profession, []).append(item.name)
    payload = _professions_payload(session)
    known = known_recipes(payload)
    rows: list[ProfessionRow] = []
    for entry, primary in _professions(payload):
        name = fields.name(fields.get(entry, "profession", "name"))
        if not name:
            continue
        tier = _tier(entry)
        skill = fields.as_int(fields.get(tier, "skill_points"))
        cap = fields.as_int(fields.get(tier, "max_skill_points"))
        current, upcoming = _rank_for(cap, ranks)
        rows.append(
            ProfessionRow(
                name=name,
                primary=primary,
                skill=skill,
                max_skill=cap,
                rank=current.name if current else None,
                next_rank=NextRank(
                    **upcoming.model_dump(),
                    skill_ready=skill is not None and skill >= upcoming.train_at_skill,
                    level_ready=level is not None and level >= upcoming.train_at_level,
                )
                if upcoming
                else None,
                note=data.notes.get(name),
                known_recipes=sum(r.profession == name for r in known),
                crafted_gear=sorted(gear.get(name, [])),
            )
        )
    return ProfessionsView(level=level, professions=rows)


class CraftingRefresh(BaseModel):
    recipes_fetched: int = 0
    items_fetched: int = 0
    errors: list[str] = []


def refresh_crafting(
    session: Session,
    settings: Settings,
    *,
    http: httpx.Client | None = None,
    force: bool = False,
    pause: float = 0.0,
) -> CraftingRefresh:
    """Fetch the recipes the character knows, then the items they make, where not cached
    in the last 30 days. Best effort: errors are returned, never raised."""
    outcome = CraftingRefresh()
    recipes = known_recipes(_professions_payload(session))
    if not recipes:
        return outcome
    cutoff = utcnow() - CRAFTING_MAX_AGE

    def fresh(row: CraftingRecipe | BlizzardItem | None) -> bool:
        return row is not None and not force and as_utc(row.fetched_at) >= cutoff

    try:
        token = app_token(session, settings, http)
    except (httpx.HTTPError, CredentialsError) as error:
        outcome.errors.append(f"Blizzard token: {error}")
        return outcome
    namespace = settings.static_namespace
    with BlizzardClient(settings, token, http=http) as client:
        wanted = [r for r in recipes if not fresh(session.get(CraftingRecipe, r.recipe_id))]
        job = JobLog(logger, "Blizzard crafting recipes", len(wanted))
        for index, recipe in enumerate(wanted, start=1):
            job.step(index)
            if pause and index > 1:
                time.sleep(pause)
            result = client.get("recipe", f"/data/wow/recipe/{recipe.recipe_id}", namespace)
            if result.status != 200 and result.status != 404:
                outcome.errors.append(f"recipe {recipe.recipe_id}: HTTP {result.status}")
                continue
            save_now(
                session,
                CraftingRecipe(
                    recipe_id=recipe.recipe_id,
                    profession=recipe.profession,
                    found=result.status == 200,
                    payload=result.body if result.status == 200 else None,
                    fetched_at=utcnow(),
                ),
            )
            outcome.recipes_fetched += 1
        job.done(f"{outcome.recipes_fetched} fetched", outcome.errors)

        item_ids = sorted(set(_crafted_ids(session).values()))
        wanted_items = [i for i in item_ids if not fresh(session.get(BlizzardItem, i))]
        job = JobLog(logger, "Blizzard crafted items", len(wanted_items))
        for index, item_id in enumerate(wanted_items, start=1):
            job.step(index)
            if pause and index > 1:
                time.sleep(pause)
            result = client.get("item", f"/data/wow/item/{item_id}", namespace)
            if result.status != 200 and result.status != 404:
                outcome.errors.append(f"item {item_id}: HTTP {result.status}")
                continue
            save_now(
                session,
                BlizzardItem(
                    item_id=item_id,
                    found=result.status == 200,
                    payload=result.body if result.status == 200 else None,
                    fetched_at=utcnow(),
                ),
            )
            outcome.items_fetched += 1
        job.done(f"{outcome.items_fetched} fetched", outcome.errors)
    return outcome


def crafted_details(items: Iterable[CraftedItem]) -> Mapping[int, CompanionInfo]:
    return {item.item_id: item.info for item in items}
