"""Owned, not equipped (#186, ADR 0052): items in the bags or bank, from the addon's game
data, flagged on the upgrades, targets and dungeon drops that name them."""

from datetime import UTC, datetime

import respx
from fastapi.testclient import TestClient

from character_planner.gamedata import GameData, Item, Items
from character_planner.gamedata import read_export as read
from character_planner.owned import mark_gear_plan, mark_recommendations, owned_items
from character_planner.pool import PoolItem, PoolSource
from character_planner.recommend import (
    Candidate,
    DungeonUpgrade,
    DungeonValue,
    Recommendations,
    SlotRecommendation,
)
from character_planner.views import GearPlan, OwnedItem

from .test_app import client, mock_character_api  # noqa: F401 (the client fixture)
from .test_game_data_items import with_items
from .test_items import mock_battlenet

OCTET = {"Content-Type": "application/octet-stream"}
GIRDLE = 270230  # Kindlegem Girdle: the WAIST target in gear_targets.yaml
BAGS_AT = 1794699950  # the schema example's bags capturedAt
BANK_AT = 1794600000  # and its bank's


def game(bags: list[tuple[int, int]] | None, bank: list[tuple[int, int]] | None) -> GameData:
    """The schema example with these (item id, count) entries in the bags and bank."""

    def items(entries: list[tuple[int, int]] | None, at: int) -> Items | None:
        if entries is None:
            return None
        # By the file's names, as the parser reads them.
        entry = {"container": 0, "quality": 2}
        return Items.model_validate(
            {
                "capturedAt": at,
                "items": [
                    Item.model_validate({**entry, "slot": n, "itemId": i, "count": c})
                    for n, (i, c) in enumerate(entries, start=1)
                ],
            }
        )

    base = read(with_items())
    return base.model_copy(update={"bags": items(bags, BAGS_AT), "bank": items(bank, BANK_AT)})


def test_nothing_is_owned_without_game_data() -> None:
    assert owned_items(None) == {}
    assert owned_items(game(None, None)) == {}


def test_stacks_add_up_and_the_bags_win_over_the_bank() -> None:
    owned = owned_items(
        game(bags=[(2589, 20), (2589, 7), (GIRDLE, 1)], bank=[(GIRDLE, 1), (6948, 1)])
    )
    assert owned[2589] == OwnedItem(
        where="bags", count=27, captured_at=datetime.fromtimestamp(BAGS_AT, UTC)
    )
    assert owned[GIRDLE].where == "bags"  # in both: the nearer, newer snapshot
    assert owned[6948] == OwnedItem(
        where="bank", count=1, captured_at=datetime.fromtimestamp(BANK_AT, UTC)
    )


def item(item_id: int, name: str) -> PoolItem:
    return PoolItem(item_id=item_id, name=name, sources=[PoolSource(kind="drop", dungeon="X")])


def test_upgrades_and_dungeon_drops_already_owned_are_flagged() -> None:
    girdle, other = item(GIRDLE, "Kindlegem Girdle"), item(1, "Something Else")
    rec = Recommendations(
        level=18,
        window=(15, 28),
        rows=[
            SlotRecommendation(
                slot="WAIST",
                equipped=None,
                candidates=[
                    Candidate(item=girdle, score_gain=5, usable_now=True),
                    Candidate(item=other, score_gain=3, usable_now=True),
                ],
            )
        ],
        dungeons=[
            DungeonValue(
                dungeon_id="x",
                dungeon="X",
                min_level=15,
                max_level=20,
                total_gain=5,
                upgrades=[
                    DungeonUpgrade(
                        slot="WAIST", item=girdle, score_gain=5, source=girdle.sources[0]
                    )
                ],
            )
        ],
        considered=2,
        unscored=0,
    )
    marked = mark_recommendations(rec, owned_items(game(bags=[(GIRDLE, 1)], bank=None)))
    girdle_pick, other_pick = marked.rows[0].candidates
    assert girdle_pick.owned is not None and girdle_pick.owned.where == "bags"
    assert other_pick.owned is None
    assert marked.dungeons[0].upgrades[0].owned is not None


def test_nothing_owned_leaves_the_views_as_they_are() -> None:
    plan = GearPlan(level=18, rows=[])
    assert mark_gear_plan(plan, {}) is plan


@respx.mock
def test_the_gear_plan_flags_an_owned_target_but_not_a_worn_one(client: TestClient) -> None:  # noqa: F811
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    before = client.get("/api/gear").json()
    assert all(row["owned"] is None for row in before["rows"])  # no game data yet

    upload = client.post("/api/game-data", content=with_items(GIRDLE), headers=OCTET)
    assert upload.status_code == 200, upload.text
    rows = {row["slot"]: row for row in client.get("/api/gear").json()["rows"]}
    assert rows["WAIST"]["target"]["item"] == "Kindlegem Girdle"
    assert rows["WAIST"]["owned"]["where"] == "bags"
    assert rows["WAIST"]["owned"]["count"] == 1
    assert all(row["owned"] is None for slot, row in rows.items() if slot != "WAIST")
    # A reached target is worn: never flagged as owned.
    assert all(row["owned"] is None for row in rows.values() if row["reached"])
