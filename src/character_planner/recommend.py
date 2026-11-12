"""Propose gear from the item pool: the best upgrades in reach for each slot (ADR 0007).

Every pool item the character can use (data/curated/recommend.yaml) is scored with the
stat weights and compared with what's equipped in each slot it fits. Each slot lists its
biggest score gains; dungeons are ranked by the upgrades they hold. gear_targets.yaml
stays the hand-picked plan: items it names are flagged as targets.

Targets for the character's current bracket (ADR 0014; pinned from the Upgrades tab or
edited on the Plan tab) are always listed for their slot until worn. Items dismissed in
the app (ADR 0012) join exclude_item_ids and are never suggested.
"""

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel

from character_planner.choices import Choices
from character_planner.companion import ATTRIBUTION as COMPANION_ATTRIBUTION
from character_planner.curated import GearTargets
from character_planner.pool import PoolItem, PoolSource, PoolView
from character_planner.scoring import Weights, score
from character_planner.views import EquippedItem

# The order the recommendations are shown in.
EQUIPMENT_SLOTS = [
    "HEAD",
    "NECK",
    "SHOULDER",
    "BACK",
    "CHEST",
    "WRIST",
    "HANDS",
    "WAIST",
    "LEGS",
    "FEET",
    "FINGER_1",
    "FINGER_2",
    "TRINKET_1",
    "TRINKET_2",
    "MAIN_HAND",
    "OFF_HAND",
    "RANGED",
]
PAIRED = {"Finger": ("FINGER_1", "FINGER_2"), "Trinket": ("TRINKET_1", "TRINKET_2")}
# Forever Companion item slot -> equipment slot (paired slots handled separately).
SLOT_FOR = {
    "Head": "HEAD",
    "Neck": "NECK",
    "Shoulder": "SHOULDER",
    "Back": "BACK",
    "Chest": "CHEST",
    "Wrist": "WRIST",
    "Hands": "HANDS",
    "Waist": "WAIST",
    "Legs": "LEGS",
    "Feet": "FEET",
    "Main Hand": "MAIN_HAND",
    "One-Hand": "MAIN_HAND",
    "Two-Hand": "MAIN_HAND",
    "Off Hand": "OFF_HAND",
    "Held In Off-hand": "OFF_HAND",
    "Ranged": "RANGED",
}


class UsageRules(BaseModel):
    weapon_types: list[str]
    armor_types: list[str]
    plate_from_level: int | None = 40
    two_handers: bool = False
    off_hand_types: list[str] = ["Shield"]
    levels_ahead: int = 3
    per_slot: int = 3
    # Gains at or below this are sidegrades, not worth listing (same band as gear targets).
    min_gain: float = 1.0
    exclude_item_ids: list[int] = []


class Candidate(BaseModel):
    item: PoolItem
    score_gain: float
    item_level_delta: int | None = None
    armor_delta: int | None = None
    stat_deltas: dict[str, int] = {}
    usable_now: bool  # required level reached
    is_target: bool = False  # a gear target in any bracket
    pinned: bool = False  # a target for the current bracket: listed even below the top picks


class SlotRecommendation(BaseModel):
    slot: str
    equipped: EquippedItem | None
    candidates: list[Candidate]


class DungeonUpgrade(BaseModel):
    slot: str
    item: PoolItem
    score_gain: float
    source: PoolSource  # how this dungeon gives it: boss drop or quest


class DungeonValue(BaseModel):
    dungeon_id: str
    dungeon: str
    min_level: int | None
    max_level: int | None
    total_gain: float
    upgrades: list[DungeonUpgrade]  # biggest gain first


class Recommendations(BaseModel):
    level: int | None
    window: tuple[int, int] | None
    rows: list[SlotRecommendation]
    dungeons: list[DungeonValue]
    considered: int  # usable, scored pool items
    unscored: int  # usable pool items without stat data yet
    attributions: list[dict[str, str]] = []


def load_rules(path: Path) -> UsageRules:
    with path.open(encoding="utf-8") as handle:
        return UsageRules.model_validate(yaml.safe_load(handle))


def unusable_reason(item: PoolItem, rules: UsageRules, level: int | None) -> str | None:
    """Why the character can't (or won't) wear this item; None when it's fine."""
    if item.item_id in rules.exclude_item_ids:
        return "excluded"
    slot = item.item_slot
    if slot is None or (slot not in SLOT_FOR and slot not in PAIRED):
        return "not equippable"
    if level is not None and (item.effective_level or 0) > level + rules.levels_ahead:
        return f"requires level {item.effective_level}"
    weapon = item.weapon_type
    # "Miscellaneous" covers jewelry and held-in-off-hand items, not weapons.
    if weapon not in (None, "Miscellaneous") and weapon not in rules.weapon_types:
        return f"can't use {weapon}"
    armor = (item.armor_type or "").lower()
    if armor == "plate" and (
        rules.plate_from_level is None or level is None or level < rules.plate_from_level
    ):
        return "plate not yet"
    if armor in ("cloth", "leather", "mail") and armor not in rules.armor_types:
        return f"not wearing {armor}"
    if slot == "Two-Hand" and not rules.two_handers:
        return "two-hander"
    if SLOT_FOR.get(slot) == "OFF_HAND" and item.weapon_type not in rules.off_hand_types:
        return "off hand type"
    return None


def has_stat_data(item: PoolItem) -> bool:
    return item.armor is not None or bool(item.stats) or item.dps is not None


def _item_score(weights: Weights, slot: str, item: PoolItem) -> float:
    return score(weights, slot=slot, armor=item.armor, stats=item.stats, dps=item.dps)


def _worn_score(weights: Weights, slot: str, worn: EquippedItem | None) -> float:
    if worn is None:
        return 0.0
    stats = {s.name: s.value for s in worn.stats}
    return score(weights, slot=slot, armor=worn.armor, stats=stats, dps=worn.dps)


def _candidate(
    slot: str,
    item: PoolItem,
    worn: EquippedItem | None,
    weights: Weights,
    level: int | None,
    target_ids: set[int],
    pinned_ids: set[int],
) -> Candidate:
    worn_stats = {s.name: s.value for s in worn.stats} if worn else {}
    names = sorted(set(worn_stats) | set(item.stats))
    stat_deltas = {
        n: item.stats.get(n, 0) - worn_stats.get(n, 0)
        for n in names
        if item.stats.get(n, 0) != worn_stats.get(n, 0)
    }
    worn_level = worn.item_level if worn else None
    worn_armor = worn.armor if worn else None
    return Candidate(
        item=item,
        score_gain=round(_item_score(weights, slot, item) - _worn_score(weights, slot, worn), 2),
        item_level_delta=(
            item.item_level - worn_level
            if item.item_level is not None and worn_level is not None
            else None
        ),
        armor_delta=((item.armor or 0) - (worn_armor or 0) if item.armor or worn_armor else None),
        stat_deltas=stat_deltas,
        usable_now=level is None or (item.effective_level or 0) <= level,
        is_target=item.item_id in target_ids or item.item_id in pinned_ids,
        pinned=item.item_id in pinned_ids,
    )


def _rank(c: Candidate) -> tuple[float, str]:
    return (-c.score_gain, c.item.name)


def _best(
    candidates: list[Candidate], count: int, skip: set[int], min_gain: float, worn: set[int]
) -> list[Candidate]:
    """The top upgrades, plus any pinned item not already worn, best first."""
    open_ = [c for c in candidates if c.item.item_id not in skip]
    top = sorted((c for c in open_ if c.score_gain > min_gain), key=_rank)[:count]
    shown = {c.item.item_id for c in top}
    pinned = [c for c in open_ if c.pinned and c.item.item_id not in shown | worn]
    return sorted(top + pinned, key=_rank)


def recommend(
    pool: PoolView,
    equipped: Mapping[str, EquippedItem],
    weights: Weights,
    rules: UsageRules,
    targets: GearTargets | None = None,
    choices: Choices | None = None,
) -> Recommendations:
    level = pool.level
    choices = choices or Choices()
    target_ids = set(targets.item_ids()) if targets else set()
    current = targets.for_level(level) if targets and level is not None else None
    pinned_ids = {t.item_id for t in current.targets if t.item_id} if current else set()
    pinned_ids -= choices.dismissed
    rules = rules.model_copy(
        update={"exclude_item_ids": sorted(set(rules.exclude_item_ids) | choices.dismissed)}
    )
    worn = {item.item_id for item in equipped.values() if item.item_id is not None}

    usable = [i for i in pool.items if unusable_reason(i, rules, level) is None]
    scored = [i for i in usable if has_stat_data(i)]

    by_slot: dict[str, list[Candidate]] = {slot: [] for slot in EQUIPMENT_SLOTS}
    for item in scored:
        item_slot = item.item_slot or ""
        for slot in PAIRED.get(item_slot, (SLOT_FOR.get(item_slot),)):
            if slot is not None:
                by_slot[slot].append(
                    _candidate(
                        slot, item, equipped.get(slot), weights, level, target_ids, pinned_ids
                    )
                )

    picks: dict[str, list[Candidate]] = {}
    for slot in EQUIPMENT_SLOTS:
        if slot in picks:
            continue
        pair = next((p for p in PAIRED.values() if slot in p), None)
        if pair is None:
            picks[slot] = _best(by_slot[slot], rules.per_slot, set(), rules.min_gain, worn)
            continue
        # Replace the weaker of the two first, then don't suggest its top pick twice
        # (most rings and trinkets are unique).
        weaker, stronger = sorted(pair, key=lambda s: _worn_score(weights, s, equipped.get(s)))
        picks[weaker] = _best(by_slot[weaker], rules.per_slot, set(), rules.min_gain, worn)
        first = {picks[weaker][0].item.item_id} if picks[weaker] else set()
        # A pinned ring or trinket is listed once, in the slot it would replace first.
        shown_pinned = {c.item.item_id for c in picks[weaker] if c.pinned}
        picks[stronger] = _best(
            by_slot[stronger], rules.per_slot, first | shown_pinned, rules.min_gain, worn
        )

    rows = [
        SlotRecommendation(slot=slot, equipped=equipped.get(slot), candidates=picks[slot])
        for slot in EQUIPMENT_SLOTS
    ]
    uses_companion = bool(pool.items)
    return Recommendations(
        level=level,
        window=pool.window,
        rows=rows,
        dungeons=dungeon_values(by_slot, rules.min_gain),
        considered=len(scored),
        unscored=len(usable) - len(scored),
        attributions=[COMPANION_ATTRIBUTION] if uses_companion else [],
    )


def dungeon_values(
    by_slot: Mapping[str, list[Candidate]], min_gain: float = 0.0
) -> list[DungeonValue]:
    """Rank dungeons by the best upgrade they hold for each slot, summed.

    Only upgrades usable now count: a dungeon is worth running for what you can wear.
    """
    # dungeon id -> slot -> best upgrade there
    best: dict[str, dict[str, DungeonUpgrade]] = {}
    meta: dict[str, PoolSource] = {}
    for slot, candidates in by_slot.items():
        for candidate in candidates:
            if not candidate.usable_now or candidate.score_gain <= min_gain:
                continue
            for source in candidate.item.sources:
                meta.setdefault(source.dungeon_id, source)
                slot_best = best.setdefault(source.dungeon_id, {})
                current = slot_best.get(slot)
                if current is None or candidate.score_gain > current.score_gain:
                    slot_best[slot] = DungeonUpgrade(
                        slot=slot,
                        item=candidate.item,
                        score_gain=candidate.score_gain,
                        source=source,
                    )

    values = []
    for dungeon_id, slots in best.items():
        source = meta[dungeon_id]
        # The same ring can top both finger slots; count each item once.
        unique: dict[int, DungeonUpgrade] = {}
        for upgrade in slots.values():
            kept = unique.get(upgrade.item.item_id)
            if kept is None or upgrade.score_gain > kept.score_gain:
                unique[upgrade.item.item_id] = upgrade
        ranked = sorted(unique.values(), key=lambda u: (-u.score_gain, u.item.name))
        values.append(
            DungeonValue(
                dungeon_id=dungeon_id,
                dungeon=source.dungeon,
                min_level=source.min_level,
                max_level=source.max_level,
                total_gain=round(sum(u.score_gain for u in ranked), 2),
                upgrades=ranked,
            )
        )
    values.sort(key=lambda v: -v.total_gain)
    return values
