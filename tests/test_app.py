import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner import app as app_module
from character_planner import jobs
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import CompanionItem, ItemChoice
from character_planner.recommend import UsageRules

from .conftest import FIXTURES
from .test_dungeons import mock_companion_dungeons
from .test_enchants import blizzard
from .test_enchants import store as store_recipes
from .test_items import COMPANION, companion_responder, mock_battlenet

BASE = "https://us.api.blizzard.com/profile/wow/character/brumboldt-doomlet"


def fixture(kind: str) -> object:
    return json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(settings: Settings, engine: Engine):
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


def log_in(client: TestClient) -> None:
    login = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86399})
    )
    callback = client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:5173/"


def mock_character_api() -> None:
    for kind, suffix in [
        ("profile", ""),
        ("equipment", "/equipment"),
        ("statistics", "/statistics"),
        ("professions", "/professions"),
        ("specializations", "/specializations"),
    ]:
        respx.get(f"{BASE}{suffix}").mock(return_value=httpx.Response(200, json=fixture(kind)))
    respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(404, text="Not Found"))


def test_healthz(client: TestClient) -> None:
    assert client.get("/api/healthz").json() == {"status": "ok"}


def test_login_redirects_to_battlenet(client: TestClient) -> None:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith(oauth.AUTHORIZE_URL)


def test_callback_rejects_unknown_state(client: TestClient) -> None:
    assert client.get("/auth/callback?code=c&state=forged").status_code == 400


def test_sync_requires_login(client: TestClient) -> None:
    assert client.post("/api/sync").status_code == 401


@respx.mock
def test_login_sync_and_read_end_to_end(client: TestClient) -> None:
    log_in(client)
    assert client.get("/api/status").json()["logged_in"] is True

    mock_character_api()
    mock_battlenet()  # item search + media, called by sync's catalog refresh
    statuses = client.post("/api/sync").json()
    assert statuses["profile"] == 200
    assert statuses["appearance"] == 404

    latest = client.get("/api/snapshots/latest").json()
    assert "appearance" not in latest  # failures are stored but never "latest"

    character = client.get("/api/character").json()
    assert character["level"] == 18
    assert character["specialization"]["name"] == "Protection"
    assert character["stats"]["defense"] == 91

    gear = client.get("/api/gear").json()
    assert gear["level"] == 18
    # Level 18: the level-15 targets are current, the level-20 ones are coming up.
    back = next(row for row in gear["rows"] if row["slot"] == "BACK")
    assert [u["target"]["item"] for u in back["upcoming"]] == ["Cape of the Brotherhood"]
    assert [s["slot"] for s in gear["later"]] == [
        "HEAD",
        "NECK",
        "SHOULDER",
        "FINGER_1",
        "FINGER_2",
    ]
    off_hand = next(row for row in gear["rows"] if row["slot"] == "OFF_HAND")
    assert off_hand["equipped"]["name"] == "Burnished Shield"
    assert off_hand["target"]["item"] == "Dwarven Defender"
    assert off_hand["reached"] is False
    # The level-15 shield target is item level 17; the equipped shield is 21.
    assert off_hand["target_info"]["sources"] == ["blizzard"]  # Companion 404s for it here
    assert off_hand["target_info"]["item_level"] == 17
    assert off_hand["verdict"] == "downgrade"
    assert off_hand["item_level_delta"] == -4
    assert off_hand["equipped"]["icon_url"].endswith(".jpg")
    # Kindlegem Girdle isn't in Blizzard's search; Forever Companion has it by id.
    waist = next(row for row in gear["rows"] if row["slot"] == "WAIST")
    assert waist["target_info"]["sources"] == ["companion"]
    assert waist["target_info"]["item_level"] == 18
    assert waist["verdict"] == "upgrade"  # equipped belt is ilvl 14
    assert waist["armor_delta"] == 27  # 100 vs 73
    assert waist["stat_deltas"] == {"Stamina": 7}
    # Default weights: (100 x 0.1 + 7 x 1.0) - 73 x 0.1 = 9.7
    assert (waist["score_delta"], waist["verdict_basis"]) == (9.7, "score")
    assert gear["rows"][0]["slot"] == "WAIST"  # biggest gain sorts first
    assert off_hand["verdict_basis"] == "item_level"  # no stats for it: falls back
    assert gear["attributions"][0]["name"] == "Forever Companion"

    points = client.get("/api/progress").json()["points"]
    assert [(p["level"], p["item_level"]) for p in points] == [(18, 14.6)]

    summary = client.get("/api/summary.md").text
    assert "- Level: 18" in summary
    assert "Kindlegem Girdle" in summary
    assert "outgrown (ilvl 21 -> 17)" in summary
    assert "upgrade (ilvl 14 -> 18, score +9.7); +27 armor, +7 Stamina [companion]" in summary
    assert "Forever Companion" in summary


@respx.mock
def test_items_refresh_endpoint(client: TestClient) -> None:
    mock_battlenet()
    result = client.post("/api/items/refresh").json()
    assert "Dwarven Defender" in result["found"]
    assert "Kindlegem Girdle" in result["missing"]


@respx.mock
def test_items_refresh_reports_battlenet_outage_without_failing(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(503))
    respx.get(url__startswith=COMPANION).mock(side_effect=companion_responder)
    response = client.post("/api/items/refresh")
    assert response.status_code == 200
    assert any(error.startswith("Blizzard") for error in response.json()["errors"])
    assert response.json()["companion_fetched"] >= 1  # the other source still ran


@respx.mock
def test_pool_refresh_lists_items_and_fills_target_ids(client: TestClient) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    mock_companion_dungeons()

    result = client.post("/api/pool/refresh").json()
    assert result["dungeons_fetched"] == 2
    assert result["pool_size"] >= 13  # 10 Hall of Thanes drops + 3 alliance Deadmines items
    assert result["errors"] == []

    pool = client.get("/api/pool").json()
    assert (pool["level"], pool["faction"], pool["window"]) == (18, "alliance", [15, 28])
    pool_ids = {item["item_id"] for item in pool["items"]}
    assert {271098, 271097, 5193, 2041} <= pool_ids

    # Golemguard Chest and Spiritwraith Drape have no item_id in the YAML: the pool fills
    # them in by name.
    targets = client.get("/api/targets").json()["targets"]
    ids = {t["item"]: t["item_id"] for t in targets}
    assert ids["Golemguard Chest"] == 271098
    assert ids["Spiritwraith Drape"] == 271097
    assert ids["Kindlegem Girdle"] == 270230  # from the YAML

    # Only Kindlegem Girdle has item details in this test, and it isn't in the pool, so
    # every usable pool item is unscored; the shape is still complete.
    recs = client.get("/api/recommendations").json()
    assert recs["level"] == 18
    assert len(recs["rows"]) == 17
    neck = next(row for row in recs["rows"] if row["slot"] == "NECK")
    assert neck["equipped"] is None
    off_hand = next(row for row in recs["rows"] if row["slot"] == "OFF_HAND")
    assert off_hand["equipped"]["name"] == "Burnished Shield"
    assert recs["considered"] == 0


def test_pool_is_empty_before_any_refresh(client: TestClient) -> None:
    assert client.get("/api/pool").json() == {
        "level": None,
        "faction": None,
        "window": None,
        "items": [],
    }


@respx.mock
def test_talent_plan_can_be_edited_and_reset(client: TestClient) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()  # a sync also refreshes item data
    client.post("/api/sync")

    view = client.get("/api/talents").json()
    assert (view["level"], view["available"], view["spent"]) == (18, 9, 9)
    assert view["next"] is None  # the shipped plan is the synced build
    assert view["customised"] is False

    extended = {
        "spec": "Protection",
        "steps": [
            {"talent": "Shield Specialization", "rank": 5},
            {"talent": "Anticipation", "rank": 1},
            {"talent": "Improved Revenge", "rank": 3},
            {"talent": "Deflection", "rank": 5},
        ],
    }
    view = client.put("/api/talents/plan", json=extended).json()
    assert view["customised"] is True
    # No talent trees loaded in this test, so no ids (#88).
    assert view["next"] == {"talent": "Deflection", "talent_id": None, "rank": 1, "level": 19}
    assert client.get("/api/talents").json()["planned_points"] == 14

    bad = {"spec": "Protection", "steps": [{"talent": " ", "rank": 0}]}
    assert client.put("/api/talents/plan", json=bad).status_code == 422

    assert client.delete("/api/talents/plan").json()["customised"] is False


@respx.mock
def test_enchant_catalog_refreshes_and_lists(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.get(url__startswith="https://us.api.blizzard.com/data/wow/").mock(side_effect=blizzard)
    items = respx.get(url__startswith=COMPANION).mock(
        return_value=httpx.Response(404, json={"error": "Not found"})
    )

    result = client.post("/api/enchants/refresh").json()
    assert (result["recipes_fetched"], result["errors"]) == (12, [])
    assert items.call_count == len(result["items_not_found"]) > 0  # reagents looked up

    listed = client.get("/api/enchants").json()
    assert len(listed) == 11  # the Season of Discovery recipe is left out by default
    assert len(client.get("/api/enchants", params={"include_sod": True}).json()) == 12
    boots = next(o for o in listed if o["name"] == "Enchant Boots - Minor Stamina")
    assert (boots["slots"], boots["effects"]) == (["FEET"], {"Stamina": 3.0})


def test_enchant_recommendations_from_snapshots_and_recipes(
    client: TestClient, engine: Engine
) -> None:
    empty = client.get("/api/enchants/recommendations").json()
    assert (empty["recipes"], empty["rows"]) == (0, [])  # before an enchant refresh

    for kind in ("profile", "equipment", "professions"):
        client.post("/api/snapshots/manual", json={"kind": kind, "payload": fixture(kind)})
    with Session(engine) as session:
        store_recipes(session)

    advice = client.get("/api/enchants/recommendations").json()
    assert (advice["level"], advice["recipes"]) == (18, 11)  # Season of Discovery left out
    rows = {r["slot"]: r for r in advice["rows"]}
    assert [p["option"]["name"] for p in rows["CHEST"]["picks"]] == [
        "Enchant Chest - Minor Stats",
        "Enchant Chest - Inferior Stamina",
    ]
    assert rows["CHEST"]["item"] == "Ironheart Chain"
    ranged = rows["RANGED"]  # the scope recipe isn't in this catalog, but the enchant is read
    assert ranged["current"]["text"] == "Enchanted: Scope (+1 Damage)"


def test_reads_are_empty_before_any_sync(client: TestClient) -> None:
    assert client.get("/api/character").json()["level"] is None
    assert client.get("/api/gear").json()["rows"] == []


def test_manual_snapshot_fills_gaps(client: TestClient) -> None:
    response = client.post(
        "/api/snapshots/manual", json={"kind": "professions", "payload": {"Mining": 93}}
    )
    assert response.status_code == 201
    assert client.get("/api/snapshots/latest").json()["professions"]["source"] == "manual"


def test_serves_built_frontend_when_present(
    settings: Settings, engine: Engine, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>planner</title>", encoding="utf-8")
    app = create_app(settings.model_copy(update={"frontend_dist": dist}), engine)

    with TestClient(app) as client:
        assert "<title>planner</title>" in client.get("/").text
        assert client.get("/api/healthz").json() == {"status": "ok"}  # API still wins


def test_weights_api_edit_and_reset(client: TestClient) -> None:
    initial = client.get("/api/weights").json()
    assert initial["customised"] is False
    assert initial["weights"]["Stamina"] == 1.0

    edited = client.put("/api/weights", json={"weights": {"Stamina": 2.0}}).json()
    assert edited["customised"] is True
    assert edited["weights"]["Stamina"] == 2.0
    assert edited["weights"]["Armor"] == initial["defaults"]["Armor"]  # unspecified: default

    reset = client.delete("/api/weights").json()
    assert reset["customised"] is False
    assert reset["weights"]["Stamina"] == 1.0


def test_weights_api_rejects_bad_values(client: TestClient) -> None:
    assert client.put("/api/weights", json={"weights": {"Stamina": 99}}).status_code == 422
    assert client.put("/api/weights", json={"weights": {"": 1}}).status_code == 422


def test_weight_presets_switch_save_rename_and_delete(client: TestClient) -> None:
    view = client.get("/api/weights").json()
    assert view["preset"] == "leveling-tank"
    assert [p["name"] for p in view["presets"]] == ["Leveling tank", "Dungeon tank", "Solo DPS"]

    solo = client.put("/api/weights/active", json={"key": "solo-dps"}).json()
    assert (solo["preset"], solo["weights"]["Strength"]) == ("solo-dps", 1.0)
    assert client.put("/api/weights/active", json={"key": "nope"}).status_code == 404

    # Save as copies the active preset when no weights are given, then switches to it.
    response = client.post("/api/weights/presets", json={"name": "Mine"})
    assert response.status_code == 201
    mine = response.json()
    assert (mine["preset"], mine["weights"]) == ("mine", solo["weights"])
    duplicate = client.post("/api/weights/presets", json={"name": "mine"})
    assert duplicate.status_code == 400
    assert "already a preset" in duplicate.json()["detail"]
    assert client.delete("/api/weights").status_code == 400  # nothing to reset to

    renamed = client.patch("/api/weights/presets/mine", json={"name": "Questing"}).json()
    assert renamed["presets"][-1]["name"] == "Questing"
    assert client.patch("/api/weights/presets/solo-dps", json={"name": "X"}).status_code == 400

    after = client.delete("/api/weights/presets/mine").json()
    assert after["preset"] == "leveling-tank"
    assert client.delete("/api/weights/presets/mine").status_code == 404


def test_presets_change_the_scores(client: TestClient) -> None:
    client.post(
        "/api/snapshots/manual", json={"kind": "equipment", "payload": fixture("equipment")}
    )
    progress_tank = client.get("/api/progress").json()
    client.put("/api/weights/active", json={"key": "solo-dps"})
    progress_dps = client.get("/api/progress").json()
    assert progress_tank["points"][-1]["gear_score"] != progress_dps["points"][-1]["gear_score"]


def test_items_can_be_dismissed_and_suggested_again(client: TestClient) -> None:
    assert client.get("/api/choices").json() == []

    client.put("/api/choices/270230", json={"choice": "dismissed", "name": "Kindlegem Girdle"})
    choices = client.put("/api/choices/5193", json={"choice": "dismissed", "name": " Cape "}).json()
    assert [(c["item_id"], c["choice"], c["name"]) for c in choices] == [
        (5193, "dismissed", "Cape"),
        (270230, "dismissed", "Kindlegem Girdle"),
    ]
    # Pins are gear targets now (ADR 0014), not choices.
    target = {"choice": "target", "name": "Cape"}
    assert client.put("/api/choices/5193", json=target).status_code == 422

    assert [c["item_id"] for c in client.delete("/api/choices/5193").json()] == [270230]
    assert client.delete("/api/choices/5193").status_code == 404
    # The recommendations still build with choices stored and no pool.
    assert client.get("/api/recommendations").status_code == 200


def test_gear_targets_can_be_edited_and_reset(client: TestClient) -> None:
    default = client.get("/api/targets").json()
    assert client.get("/api/gear").json()["targets_customised"] is False

    edited = {
        "targets": [
            {"slot": "BACK", "item": "Spiritwraith Drape", "level": 15},
            {"slot": "CHEST", "item": "Tunic of Westfall", "source": "Quest"},
            {"slot": "BACK", "item": " Cape of the Brotherhood ", "item_id": 5193, "level": 20},
        ]
    }
    saved = client.put("/api/targets", json=edited).json()
    assert [(t["item"], t["level"], t["priority"]) for t in saved["targets"]] == [
        ("Spiritwraith Drape", 15, 1),
        ("Tunic of Westfall", None, 1),
        ("Cape of the Brotherhood", 20, 2),
    ]
    assert client.get("/api/targets").json() == saved
    assert client.get("/api/gear").json()["targets_customised"] is True

    assert client.delete("/api/targets").json() == default
    assert client.get("/api/gear").json()["targets_customised"] is False


@pytest.mark.parametrize(
    "target",
    [
        {"slot": "TABARD", "item": "x"},
        {"slot": "BACK", "item": ""},
        {"slot": "BACK", "item": "x", "level": 0},
        {"slot": "BACK", "item": "x", "level": 81},
    ],
)
def test_gear_target_edits_are_validated(client: TestClient, target: dict[str, object]) -> None:
    assert client.put("/api/targets", json={"targets": [target]}).status_code == 422
    assert client.get("/api/gear").json()["targets_customised"] is False


@respx.mock
def test_pinning_adds_pool_items_to_their_slot(client: TestClient) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    mock_companion_dungeons()
    client.post("/api/pool/refresh")

    pinned = client.post("/api/targets/pins", json={"item_id": 2042, "slot": "MAIN_HAND"}).json()
    main_hand = [t for t in pinned["targets"] if t["slot"] == "MAIN_HAND"]
    staff = main_hand[-1]
    assert [t["priority"] for t in main_hand] == [1, 2, 3]  # after the two planned weapons
    assert (staff["item"], staff["item_id"], staff["level"]) == ("Staff of Westfall", 2042, None)
    assert "Deadmines" in staff["source"]
    assert staff["pinned"] is True
    # Pinning again changes nothing.
    again = client.post("/api/targets/pins", json={"item_id": 2042, "slot": "MAIN_HAND"}).json()
    assert again == pinned

    # A planned target ("Pin" on Upgrades) only gets the mark.
    marked = client.post("/api/targets/pins", json={"item_id": 5193, "slot": "BACK"}).json()
    capes = [t for t in marked["targets"] if t["item_id"] == 5193]
    assert [(c["level"], c["pinned"]) for c in capes] == [(20, True)]

    unknown = client.post("/api/targets/pins", json={"item_id": 999999, "slot": "BACK"})
    assert unknown.status_code == 404
    bad_slot = client.post("/api/targets/pins", json={"item_id": 5193, "slot": "TABARD"})
    assert bad_slot.status_code == 422

    unpinned = client.delete("/api/targets/pins/5193").json()
    cape = next(t for t in unpinned["targets"] if t["item_id"] == 5193)
    assert cape["pinned"] is False  # still a target; remove it in the editor
    assert client.delete("/api/targets/pins/5193").status_code == 404


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/choices/1", {"choice": "maybe", "name": "x"}),
        ("/api/choices/1", {"choice": "target", "name": ""}),
        ("/api/choices/1", {"choice": "target", "name": "x" * 121}),
        ("/api/choices/0", {"choice": "target", "name": "x"}),
    ],
)
def test_choices_are_validated(client: TestClient, path: str, body: dict[str, str]) -> None:
    assert client.put(path, json=body).status_code == 422
    assert client.get("/api/choices").json() == []


@respx.mock
def test_items_pinned_before_targets_were_editable_move_into_them(
    client: TestClient, settings: Settings, engine: Engine
) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    mock_companion_dungeons()
    client.post("/api/pool/refresh")
    with Session(engine) as session:
        # The pin's slot comes from Companion details; borrow the girdle's for the cape.
        details = json.loads((FIXTURES / "companion_item_270230.json").read_text("utf-8"))
        session.merge(CompanionItem(item_id=5193, found=True, payload=details))
        session.add(ItemChoice(item_id=5193, choice="target", name="Cape of the Brotherhood"))
        session.add(ItemChoice(item_id=999999, choice="target", name="Not in the pool"))
        session.commit()
        assert jobs.migrate_target_choices(session, settings) == 1
        assert jobs.migrate_target_choices(session, settings) == 0

    # The cape is already a planned target, so the old pin marks it.
    targets = client.get("/api/targets").json()["targets"]
    assert [(t["slot"], t["pinned"]) for t in targets if t["item_id"] == 5193] == [("BACK", True)]
    assert client.get("/api/gear").json()["targets_customised"] is True


def test_upgrades_rules_can_be_edited_and_reset(client: TestClient, engine: Engine) -> None:
    default = client.get("/api/rules").json()
    assert default["customised"] is False
    assert default["rules"] == default["defaults"]
    assert "Wand" in default["weapon_type_options"]
    assert "exclude_item_ids" not in default["rules"]

    edited = default["rules"] | {"weapon_types": ["Gun", "Axe"], "per_slot": 1, "min_gain": 2.5}
    saved = client.put("/api/rules", json=edited).json()
    assert saved["customised"] is True
    assert (saved["rules"]["weapon_types"], saved["rules"]["per_slot"]) == (["Axe", "Gun"], 1)
    assert saved["defaults"] == default["defaults"]
    # Recommendations and enchants read the stored rules.
    with Session(engine) as session:
        assert (
            app_module.get_rules(session, UsageRules.model_validate(default["defaults"])).per_slot
            == 1
        )
    assert client.get("/api/recommendations").status_code == 200

    reset = client.delete("/api/rules").json()
    assert reset["customised"] is False
    assert reset["rules"] == default["rules"]


@pytest.mark.parametrize(
    "change",
    [
        {"weapon_types": ["Lightsaber"]},
        {"per_slot": 0},
        {"min_gain": -1},
        {"armor_types": ["plate"]},
    ],
)
def test_upgrades_rules_edits_are_validated(client: TestClient, change: dict[str, object]) -> None:
    rules = client.get("/api/rules").json()["rules"]
    assert client.put("/api/rules", json=rules | change).status_code == 422
    assert client.get("/api/rules").json()["customised"] is False


@respx.mock
def test_guest_mode_uses_the_shipped_rules_and_stores_nothing(
    client: TestClient, engine: Engine
) -> None:
    log_in(client)
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    mock_companion_dungeons()
    client.post("/api/pool/refresh")
    with Session(engine) as session:
        # Give the cape item details (the girdle's: mail, stamina) so it can be scored.
        details = json.loads((FIXTURES / "companion_item_270230.json").read_text("utf-8"))
        session.merge(CompanionItem(item_id=5193, found=True, payload=details))
        session.commit()

    options = client.get("/api/guest").json()
    classes = {c["key"]: c for c in options["classes"]}
    assert list(classes)[:2] == ["warrior", "druid"]  # Warrior first, then by name (#80)
    assert classes["warrior"]["presets"][0]["key"] == "leveling-tank"
    assert classes["warlock"]["presets"][0]["key"] == "warlock-leveling"
    assert options["factions"] == ["alliance", "horde"]

    guest = client.get("/api/guest/recommendations", params={"level": 18}).json()
    assert (guest["level"], guest["window"]) == (18, [15, 28])
    assert all(row["equipped"] is None for row in guest["rows"])  # every slot empty
    assert guest["considered"] == 1
    waist = next(row for row in guest["rows"] if row["slot"] == "WAIST")
    assert [c["item"]["item_id"] for c in waist["candidates"]] == [5193]

    # Edits made in the app change the character's upgrades, not the guest's.
    rules = client.get("/api/rules").json()["rules"]
    no_armor = rules | {"armor_types": [], "weapon_types": []}
    assert client.get("/api/recommendations").json()["considered"] == 1
    assert client.put("/api/rules", json=no_armor).status_code == 200
    client.put("/api/choices/5193", json={"choice": "dismissed", "name": "Cape"})
    assert client.get("/api/recommendations").json()["considered"] == 0
    again = client.get("/api/guest/recommendations", params={"level": 18}).json()
    assert again == guest

    horde = client.get("/api/guest/recommendations", params={"level": 18, "faction": "horde"})
    assert horde.status_code == 200
    preset = client.get("/api/guest/recommendations", params={"level": 18, "preset": "solo-dps"})
    assert preset.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"level": 18, "class": "death-knight"},
        {"level": 18, "preset": "nope"},
        {"level": 0},
        {"level": 81},
        {"level": 18, "faction": "neutral"},
        {},
    ],
)
def test_guest_mode_choices_are_validated(client: TestClient, params: dict[str, object]) -> None:
    response = client.get("/api/guest/recommendations", params=params)
    assert response.status_code == 422


def test_guest_mode_works_before_any_login_or_pool(client: TestClient) -> None:
    guest = client.get("/api/guest/recommendations", params={"level": 30}).json()
    assert (guest["considered"], guest["unscored"]) == (0, 0)


def _requested_item_ids() -> set[int]:
    prefix = "https://forevercompanion.io/api/v1/items/"
    return {
        int(str(call.request.url).removeprefix(prefix))
        for call in respx.calls
        if str(call.request.url).startswith(prefix)
    }


@respx.mock
def test_a_pool_refresh_can_ask_for_a_level_window(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """No character (a fresh install, guest mode): a level keeps the refresh to its window
    instead of the whole pool (#48)."""
    mock_companion_dungeons()
    respx.get(url__startswith="https://forevercompanion.io/api/v1/items/").mock(
        return_value=httpx.Response(404, json={})
    )
    # Level 5's window (2-15) reaches Hall of Thanes (13-18), not the Deadmines (17+).
    with caplog.at_level(logging.INFO):
        result = client.post("/api/pool/refresh", params={"level": 5}).json()
    asked = _requested_item_ids()
    assert 0 < result["in_window"] < result["pool_size"]
    assert len(asked) == result["in_window"]
    assert not asked & {5193, 2041, 2042}  # Deadmines items
    assert any("level 5 (asked for), window (2, 15)" in r.getMessage() for r in caplog.records)

    # Without a level and with no character: the whole pool, as before.
    respx.calls.reset()
    whole = client.post("/api/pool/refresh", params={"force": True}).json()
    assert whole["in_window"] == whole["pool_size"]
    assert {5193, 2041} <= _requested_item_ids()


@pytest.mark.parametrize("level", [0, 81])
def test_a_pool_refresh_level_is_bounded(client: TestClient, level: int) -> None:
    assert client.post("/api/pool/refresh", params={"level": level}).status_code == 422


def test_about_gives_the_footer_its_credits_source_and_version(
    settings: Settings, engine: Engine
) -> None:
    """#43: one footer credits Forever Companion and its sources and links the source."""
    with TestClient(create_app(settings, engine)) as client:
        about = client.get("/api/about").json()
    assert about["source_url"] == "https://github.com/thechainercygnus/character-planner"
    assert about["version"]
    assert (about["data"]["name"], about["data"]["url"]) == (
        "Forever Companion",
        "https://forevercompanion.io",
    )
    assert [s["name"] for s in about["data"]["sources"]] == [
        "ForeverChanges",
        "Wowhead",
        "Zockify",
    ]


def test_a_fork_points_the_source_link_at_itself(settings: Settings, engine: Engine) -> None:
    fork = settings.model_copy(update={"source_url": "https://git.example.org/me/planner"})
    with TestClient(create_app(fork, engine)) as client:
        assert client.get("/api/about").json()["source_url"] == "https://git.example.org/me/planner"


@pytest.mark.parametrize("value", ["javascript:alert(1)", "ftp://x", "https://a b", ""])
def test_the_source_url_must_be_a_web_address(value: str) -> None:
    with pytest.raises(ValueError, match="SOURCE_URL"):
        Settings(source_url=value, _env_file=None)  # pyright: ignore[reportCallIssue]
