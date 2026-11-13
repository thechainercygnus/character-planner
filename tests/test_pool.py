import json

import httpx
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.companion import BASE_URL, CompanionInfo
from character_planner.curated import GearTarget, GearTargets
from character_planner.dungeons import Dungeon, Loot, QuestReward, parse_dungeon
from character_planner.pool import (
    build_pool,
    in_window,
    level_window,
    pool_view,
    refresh_pool,
    resolve_target_ids,
    slot_key,
    with_details,
)

from .conftest import FIXTURES
from .test_dungeons import DEADMINES, HALL, LIST, mock_companion_dungeons

KINDLEGEM = json.loads((FIXTURES / "companion_item_270230.json").read_text(encoding="utf-8"))


def dungeon(**overrides: object) -> Dungeon:
    base: dict[str, object] = {
        "id": "rfc",
        "name": "Ragefire Chasm",
        "min_level": 13,
        "max_level": 18,
    }
    return Dungeon.model_validate(base | overrides)


def test_build_pool_merges_sources_and_filters_quest_faction() -> None:
    deadmines = parse_dungeon(DEADMINES)
    assert deadmines is not None
    pool = build_pool([deadmines], faction="alliance")

    assert set(pool) == {5193, 2041, 2042}  # the horde-only reward is left out
    cape = pool[5193]
    assert (cape.slot, cape.quality) == ("back", "RARE")
    assert cape.sources[0].kind == "drop"
    assert cape.sources[0].detail == "Edwin VanCleef"
    tunic = pool[2041].sources[0]
    assert (tunic.kind, tunic.detail, tunic.choice) == ("quest", "The Defias Brotherhood", True)

    assert 9999 in build_pool([deadmines], faction=None)  # unknown faction: keep everything


def test_item_from_two_dungeons_keeps_both_sources() -> None:
    shared = Loot(item_id=1, name="Shared Ring", slot="finger")
    pool = build_pool(
        [dungeon(loot=[shared]), dungeon(id="wc", name="Wailing Caverns", loot=[shared])]
    )
    assert [s.dungeon for s in pool[1].sources] == ["Ragefire Chasm", "Wailing Caverns"]


def test_level_window_overlap() -> None:
    pool = build_pool(
        [
            dungeon(loot=[Loot(item_id=1, name="Low")], min_level=8, max_level=14),
            dungeon(id="mid", loot=[Loot(item_id=2, name="Mid")], min_level=17, max_level=24),
            dungeon(id="high", loot=[Loot(item_id=3, name="High")], min_level=29, max_level=38),
            dungeon(id="unknown", loot=[Loot(item_id=4, name="?")], min_level=None, max_level=None),
        ]
    )
    window = level_window(18)
    assert window == (15, 28)
    assert {i for i, item in pool.items() if in_window(item, window)} == {2, 4}


def test_resolve_target_ids_by_unique_name() -> None:
    pool = build_pool(
        [
            dungeon(
                loot=[
                    Loot(item_id=271098, name="Golemguard Chest"),
                    Loot(item_id=10, name="Twin Name"),
                ],
                rewards=[QuestReward(item_id=11, name="Twin Name", quest="Q")],
            )
        ]
    )
    targets = GearTargets(
        targets=[
            GearTarget(slot="CHEST", item="golemguard chest", source="HoT"),
            GearTarget(slot="LEGS", item="Twin Name", source="?"),
            GearTarget(slot="CHEST", item="Golemguard Chest", source="?", item_id=5),
        ]
    )
    resolved = resolve_target_ids(targets, pool).targets
    assert [t.item_id for t in resolved] == [271098, None, 5]  # ambiguous: left alone
    assert targets.targets[0].item_id is None  # original untouched


@respx.mock
def test_refresh_pool_fetches_details_in_window_only(engine: Engine) -> None:
    mock_companion_dungeons()
    items = respx.get(url__startswith=f"{BASE_URL}/items/").mock(
        return_value=httpx.Response(404, json={"error": "Not found"})
    )
    with Session(engine) as session, httpx.Client() as http:
        result = refresh_pool(session, level=18, faction="alliance", http=http, pause=0)
        again = refresh_pool(session, level=18, faction="alliance", http=http, pause=0)

    parsed = [parse_dungeon(HALL), parse_dungeon(DEADMINES)]
    expected = build_pool([d for d in parsed if d is not None], "alliance")
    in_reach = [i for i in expected.values() if in_window(i, level_window(18))]
    assert result.dungeons_listed == 2
    assert result.dungeons_fetched == 2
    assert result.pool_size == len(expected)
    assert {5193, 2041, 2042, 271098} <= set(expected)  # drops and alliance rewards
    assert 9999 not in expected  # horde-only reward
    assert result.in_window == len(in_reach)
    assert items.call_count == len(in_reach)
    assert result.errors == []
    assert again.dungeons_fetched == 0
    assert again.items_fetched == 0
    assert items.call_count == len(in_reach)  # 404s are cached too


@respx.mock
def test_refresh_pool_skips_items_outside_the_window(engine: Engine) -> None:
    only_deadmines = {"data": [entry for entry in LIST["data"] if entry["id"] == "the-deadmines"]}
    respx.get(f"{BASE_URL}/rares").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/class-quests").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(200, json=only_deadmines))
    respx.get(f"{BASE_URL}/dungeons/the-deadmines").mock(
        return_value=httpx.Response(200, json=DEADMINES)
    )
    items = respx.get(url__startswith=f"{BASE_URL}/items/").mock(return_value=httpx.Response(404))
    with Session(engine) as session, httpx.Client() as http:
        result = refresh_pool(session, level=40, faction="alliance", http=http, pause=0)
    # Level 40's window is 37-50; The Deadmines (17-26) is out of it.
    assert (result.pool_size, result.in_window) == (3, 0)
    assert items.call_count == 0


@respx.mock
def test_pool_view_adds_item_details(engine: Engine) -> None:
    respx.get(f"{BASE_URL}/rares").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/class-quests").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/dungeons").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "hall-of-thanes"}]})
    )
    respx.get(f"{BASE_URL}/dungeons/hall-of-thanes").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": "hall-of-thanes",
                    "name": "Hall of Thanes",
                    "minLevel": 16,
                    "maxLevel": 22,
                    "loot": [{"itemId": 270230, "name": "Kindlegem Girdle", "slot": "waist"}],
                }
            },
        )
    )
    respx.get(f"{BASE_URL}/items/270230").mock(return_value=httpx.Response(200, json=KINDLEGEM))
    with Session(engine) as session, httpx.Client() as http:
        refresh_pool(session, level=18, faction="alliance", http=http, pause=0)
        view = pool_view(session, 18, "alliance")

    assert view.window == (15, 28)
    (girdle,) = view.items
    assert (girdle.item_level, girdle.required_level, girdle.armor_type) == (18, 13, "Mail")
    assert girdle.armor == 100
    assert girdle.stats == {"Stamina": 7}


def test_quest_rewards_take_their_slot_from_item_details() -> None:
    pool = build_pool([dungeon(rewards=[QuestReward(item_id=7, name="Hilt", quest="Q")])])
    assert pool[7].slot is None
    detailed = with_details(pool[7], CompanionInfo(item_id=7, slot="Main Hand"))
    assert detailed.slot == "main-hand"
    assert slot_key("Waist") == "waist"
    assert slot_key(None) is None
