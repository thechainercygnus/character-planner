"""Quest chains for quest-reward upgrades (#7, ADR 0028)."""

import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner.companion import BASE_URL
from character_planner.db import CompanionQuest
from character_planner.dungeons import Dungeon, QuestReward, parse_dungeon
from character_planner.pool import build_pool, pool_view, refresh_pool, undescribed_steps
from character_planner.quests import (
    QuestStep,
    chain_level,
    parse_prerequisites,
    parse_quest,
    refresh_quests,
    stored_quests,
)

from .conftest import FIXTURES
from .test_dungeons import HALL, QUEST_NOT_FOUND


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


KRAUL = fixture("companion_dungeon_razorfen_kraul.json")
LONEBROW = fixture("companion_quest_1100.json")  # an elite quest: GET /quests/1100


def parsed(payload: Any) -> Dungeon:
    dungeon = parse_dungeon(payload)
    assert dungeon is not None
    return dungeon


def quest_source(pool: dict[int, Any], item_id: int, quest: str) -> Any:
    return next(s for s in pool[item_id].sources if s.kind == "quest" and s.detail == quest)


def test_parse_an_elite_quest_by_id() -> None:
    step = parse_quest(LONEBROW)
    assert step is not None
    assert (step.quest_id, step.name, step.level, step.min_level) == (
        1100,
        "Lonebrow's Journal",
        34,
        29,
    )
    # Elite quests name their zone; this one has no giver or location.
    assert (step.zone, step.giver, step.location, step.dungeon) == (
        "Thousand Needles",
        None,
        None,
        None,
    )
    assert step.wowhead == "https://www.wowhead.com/forever/quest=1100"
    assert step.known


def test_a_not_found_body_is_not_a_quest() -> None:
    assert parse_quest(QUEST_NOT_FOUND) is None


def test_dungeon_quests_are_described_from_the_dungeon_data() -> None:
    quests = {q.quest_id: q for q in parsed(HALL).quests}
    incursion = quests[96393]
    assert (incursion.giver, incursion.location, incursion.dungeon) == (
        "Earthseer Farsen",
        "Dun Morogh",
        "Hall of Thanes",
    )
    assert (incursion.level, incursion.min_level) == (16, 9)


def test_prerequisites_keep_their_order_and_side_by_side_steps() -> None:
    refs = parse_prerequisites(
        [
            [{"questId": 1, "name": "First"}],
            [{"questId": 2, "name": "Second A"}, {"questId": None, "name": "Second B"}],
            [{"questId": 3}],  # no name: dropped, and the empty step with it
            "not a step",
        ]
    )
    assert refs == [[(1, "First")], [(2, "Second A"), (None, "Second B")]]
    assert parse_prerequisites(None) == []


def test_a_reward_quest_carries_its_chain() -> None:
    pool = build_pool([parsed(HALL)], "alliance")
    source = quest_source(pool, 279894, "Old Ironforge Incursion")  # Calibrated Blunderbuss
    assert source.quest is not None
    assert (source.quest.giver, source.quest.location) == ("Earthseer Farsen", "Dun Morogh")
    # Underground Map is a zone quest: Forever Companion only names it.
    [[step]] = source.chain
    assert (step.quest_id, step.name, step.known) == (96391, "Underground Map", False)
    assert step.wowhead == "https://www.wowhead.com/forever/quest=96391"


def test_chain_steps_are_described_from_quests_fetched_by_id() -> None:
    kraul = parsed(KRAUL)
    lonebrow = parse_quest(LONEBROW)
    assert lonebrow is not None

    unknown = quest_source(build_pool([kraul], "alliance"), 4197, "The Crone of the Kraul")
    assert [[s.known for s in step] for step in unknown.chain] == [[False]]

    pool = build_pool([kraul], "alliance", {1100: lonebrow})
    [[step]] = quest_source(pool, 4197, "The Crone of the Kraul").chain  # Berylline Pads
    assert (step.name, step.zone, step.known) == ("Lonebrow's Journal", "Thousand Needles", True)
    # The Horde quest for the same pads has no chain.
    assert quest_source(build_pool([kraul], "horde"), 4197, "A Vengeful Fate").chain == []


def test_a_step_that_is_another_dungeons_quest_is_described_from_it() -> None:
    before = Dungeon(
        id="hall-of-thanes",
        name="Hall of Thanes",
        min_level=13,
        max_level=18,
        quests=[QuestStep(quest_id=96393, name="Old Ironforge Incursion", min_level=9, known=True)],
    )
    after = Dungeon(
        id="later",
        name="Later Dungeon",
        min_level=20,
        max_level=26,
        rewards=[
            QuestReward(
                item_id=1,
                name="Ring",
                quest="Next",
                min_level=20,
                prerequisites=[[(96393, "Old Ironforge Incursion")]],
            )
        ],
    )
    [[step]] = build_pool([after, before])[1].sources[0].chain
    assert step.known and step.min_level == 9
    assert undescribed_steps([after, before], build_pool([after, before]).values()) == []


@pytest.mark.parametrize(
    ("step_level", "expected"),
    [
        (24, 24),  # the chain starts above the quest and the dungeon: it sets the level
        (12, 21),  # below both: the quest's own pickup level
        (None, 21),  # unknown: as before
    ],
)
def test_the_chains_highest_step_feeds_the_items_level(
    step_level: int | None, expected: int
) -> None:
    known = {7: QuestStep(quest_id=7, name="Earlier", min_level=step_level, known=True)}
    dungeon = Dungeon(
        id="d",
        name="D",
        min_level=18,
        max_level=26,
        rewards=[
            QuestReward(
                item_id=1,
                name="Boots",
                quest="Last",
                min_level=21,
                prerequisites=[[(7, "Earlier")]],
            )
        ],
    )
    assert build_pool([dungeon], quests=known)[1].effective_level == expected


def test_chain_level_uses_the_pickup_level_then_the_quest_level() -> None:
    chain = [
        [QuestStep(name="a", min_level=10, level=14)],
        [QuestStep(name="b", level=17), QuestStep(name="c")],
    ]
    assert chain_level(chain) == 17
    assert chain_level([]) is None


@respx.mock
def test_refresh_quests_caches_found_and_not_found(engine: Engine) -> None:
    lonebrow = respx.get(f"{BASE_URL}/quests/1100").mock(
        return_value=httpx.Response(200, json=LONEBROW)
    )
    zone = respx.get(f"{BASE_URL}/quests/96391").mock(
        return_value=httpx.Response(404, json=QUEST_NOT_FOUND)
    )
    with Session(engine) as session, httpx.Client() as http:
        first = refresh_quests(session, [1100, 96391, 1100], http=http)
        again = refresh_quests(session, [1100, 96391], http=http)
        rows = {r.quest_id: r.found for r in session.exec(select(CompanionQuest)).all()}
        stored = stored_quests(session)

    assert (first.fetched, first.not_found, first.errors) == ([1100], [96391], [])
    assert (again.fetched, again.not_found) == ([], [])
    assert (lonebrow.call_count, zone.call_count) == (1, 1)
    assert rows == {1100: True, 96391: False}
    assert set(stored) == {1100}


@respx.mock
def test_refresh_quests_stops_at_a_rate_limit(engine: Engine) -> None:
    limited = respx.get(f"{BASE_URL}/quests/1").mock(return_value=httpx.Response(429))
    later = respx.get(f"{BASE_URL}/quests/2").mock(return_value=httpx.Response(200, json=LONEBROW))
    broken = respx.get(f"{BASE_URL}/quests/3").mock(return_value=httpx.Response(503))
    with Session(engine) as session, httpx.Client() as http:
        stopped = refresh_quests(session, [1, 2], http=http)
        failed = refresh_quests(session, [3], http=http)
        assert session.exec(select(CompanionQuest)).all() == []

    assert stopped.errors == ["quest 1: rate limited; stopping this batch"]
    assert (limited.call_count, later.call_count) == (1, 0)
    assert failed.errors == ["quest 3: HTTP 503"]  # not cached: tried again next time
    assert broken.call_count == 1


@respx.mock
def test_refresh_quests_without_ids_makes_no_requests(engine: Engine) -> None:
    with Session(engine) as session:
        assert refresh_quests(session, []).fetched == []


@respx.mock
def test_pool_refresh_looks_up_undescribed_steps_once(engine: Engine) -> None:
    listing = {"data": [{"id": "razorfen-kraul", "status": "launch"}]}
    respx.get(f"{BASE_URL}/rares").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/dungeons").mock(return_value=httpx.Response(200, json=listing))
    respx.get(f"{BASE_URL}/dungeons/razorfen-kraul").mock(
        return_value=httpx.Response(200, json=KRAUL)
    )
    respx.get(url__startswith=f"{BASE_URL}/items/").mock(return_value=httpx.Response(404))
    lonebrow = respx.get(f"{BASE_URL}/quests/1100").mock(
        return_value=httpx.Response(200, json=LONEBROW)
    )
    # Fire Hardened Mail's chain starts with The Shieldsmith, a zone quest; it has no
    # reward items, so it's not in the pool and isn't looked up.
    shieldsmith = respx.get(f"{BASE_URL}/quests/1702").mock(return_value=httpx.Response(404))
    with Session(engine) as session, httpx.Client() as http:
        first = refresh_pool(session, level=30, faction="alliance", http=http, pause=0)
        again = refresh_pool(session, level=30, faction="alliance", http=http, pause=0)
        view = pool_view(session, 30, "alliance")

    assert (first.quests_fetched, again.quests_fetched) == (1, 0)
    assert first.errors == []
    assert (lonebrow.call_count, shieldsmith.call_count) == (1, 0)
    pads = next(i for i in view.items if i.item_id == 4197)
    [[step]] = quest_source({4197: pads}, 4197, "The Crone of the Kraul").chain
    assert (step.name, step.zone) == ("Lonebrow's Journal", "Thousand Needles")
