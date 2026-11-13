"""Look ahead to the next levels (#4, ADR 0032)."""

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from character_planner.class_quests import ClassQuestChecklist, ClassQuestRow
from character_planner.crafting import NextRank, ProfessionRow, ProfessionsView
from character_planner.curated import GearTarget
from character_planner.dungeons import Dungeon, parse_dungeon
from character_planner.lookahead import LookAhead, look_ahead
from character_planner.talents import PlanStep, TalentPlan, compare
from character_planner.views import GearPlan, SlotOutlook, UpcomingTarget

from .test_app import client, fixture  # noqa: F401 (the client fixture)
from .test_class_quests import store_list
from .test_dungeons import HALL

# Dungeons as Forever Companion lists them (2026-11-13): level ranges, zones and access.
SHADOWFANG = Dungeon(
    id="shadowfang-keep",
    name="Shadowfang Keep",
    min_level=20,
    max_level=30,
    zone="Silverpine Forest",
)
STOCKADE = Dungeon(
    id="the-stockade",
    name="The Stockade",
    min_level=24,
    max_level=32,
    zone="Stormwind City",
    access="alliance",
)
RAGEFIRE = Dungeon(
    id="ragefire-chasm",
    name="Ragefire Chasm",
    min_level=13,
    max_level=18,
    zone="Orgrimmar",
    access="horde",
)
DALARAN = Dungeon(
    id="city-of-dalaran",
    name="City of Dalaran",
    min_level=28,
    max_level=33,
    zone="Alterac Mountains",
    beta_locked=True,
)
ANNOUNCED = Dungeon(id="later", name="Announced", min_level=21, status="announced")

GEAR = GearPlan(
    level=19,
    rows=[],
    later=[
        SlotOutlook(
            slot="MAIN_HAND",
            equipped=None,
            upcoming=[
                UpcomingTarget(
                    target=GearTarget(
                        slot="MAIN_HAND",
                        item="Doomspike",
                        source="Wailing Caverns",
                        pinned=True,
                    ),
                    target_info=None,
                    level=22,
                    score_delta=15.7,
                ),
                UpcomingTarget(
                    target=GearTarget(slot="MAIN_HAND", item="Far Off", source="?"),
                    target_info=None,
                    level=40,
                ),
            ],
        )
    ],
)
# 12 planned points: the 1st at level 10, so at level 19 ten are due and points 11 and
# 12 (Toughness) come at 20 and 21; from 22 the plan has run out.
PLAN = TalentPlan(
    spec="Protection",
    steps=[
        PlanStep(talent="Shield Specialization", rank=5),
        PlanStep(talent="Anticipation", rank=5),
        PlanStep(talent="Toughness", rank=2),
    ],
)
QUESTS = ClassQuestChecklist(
    class_name="Warrior",
    level=19,
    listed=44,
    rows=[
        ClassQuestRow(
            id="warrior-fire-hardened",
            class_key="warrior",
            level=20,
            name="Yorus Barleybrew",
            giver="Yorus Barleybrew",
            reward="Fire Hardened armor pieces",
            status="soon",
        ),
        ClassQuestRow(
            id="warrior-berserker-stance",
            class_key="warrior",
            level=30,
            name="The Islander",
            essential=True,
            status="later",
        ),
        ClassQuestRow(
            id="done-one",
            class_key="warrior",
            level=21,
            name="Done already",
            done=True,
            status="done",
        ),
    ],
)
PROFESSIONS = ProfessionsView(
    level=19,
    professions=[
        ProfessionRow(
            name="Engineering",
            primary=True,
            skill=104,
            max_skill=150,
            rank="Journeyman",
            next_rank=NextRank(
                name="Expert",
                max_skill=225,
                train_at_skill=125,
                train_at_level=20,
                skill_ready=False,
                level_ready=False,
            ),
            known_recipes=19,
            crafted_gear=[],
        ),
        ProfessionRow(
            name="Cooking",
            primary=False,
            skill=94,
            max_skill=150,
            rank="Journeyman",
            next_rank=NextRank(
                name="Expert",
                max_skill=225,
                train_at_skill=125,
                train_at_level=20,
                skill_ready=False,
                level_ready=False,
            ),
            note="Expert comes from a book; Artisan from a quest in Tanaris.",
            known_recipes=11,
            crafted_gear=[],
        ),
    ],
)


def ahead(level: int | None = 19, levels: int = 5, faction: str | None = "alliance") -> LookAhead:
    hall = parse_dungeon(HALL)
    assert hall is not None
    return look_ahead(
        level,
        levels,
        faction=faction,
        dungeons=[hall, SHADOWFANG, STOCKADE, RAGEFIRE, DALARAN, ANNOUNCED],
        gear=GEAR,
        talents=compare(PLAN, None, level),
        class_quests=QUESTS,
        professions=PROFESSIONS,
    )


def titles(view: LookAhead) -> dict[int, list[str]]:
    return {group.level: [e.title for e in group.events] for group in view.groups}


def test_each_coming_level_lists_what_it_brings() -> None:
    assert titles(ahead()) == {
        20: [
            "Shadowfang Keep",
            "Class quest: Yorus Barleybrew",
            "Expert Engineering",
            "Expert Cooking",
            "Talent: Toughness rank 1",
        ],
        21: ["Talent: Toughness rank 2"],
        22: ["Main Hand: Doomspike", "Talent point"],
        23: ["Talent point"],
        24: ["The Stockade", "Talent point"],
    }


def test_event_details() -> None:
    events = {e.title: e for group in ahead().groups for e in group.events}
    assert events["Shadowfang Keep"].detail == "levels 20-30, Silverpine Forest"
    assert events["Shadowfang Keep"].link == "https://forevercompanion.io/dungeons/shadowfang-keep"
    doomspike = events["Main Hand: Doomspike"]
    assert (doomspike.detail, doomspike.pinned) == ("+15.7 score · Wailing Caverns", True)
    assert events["Class quest: Yorus Barleybrew"].detail == (
        "Fire Hardened armor pieces · Yorus Barleybrew"
    )
    assert events["Expert Engineering"].detail == "cap 225; needs 125 skill, 21 to go"
    assert events["Expert Cooking"].detail == (
        "cap 225; needs 125 skill, 31 to go. "
        "Expert comes from a book; Artisan from a quest in Tanaris."
    )


def test_faction_lock_and_announced_dungeons() -> None:
    horde = titles(ahead(level=12, levels=1, faction="horde"))
    assert horde[13][:1] == ["Ragefire Chasm"]  # Hall of Thanes is the alliance's
    alliance = titles(ahead(level=12, levels=1, faction="alliance"))
    assert alliance[13][:1] == ["Hall of Thanes"]
    unknown = titles(ahead(level=12, levels=1, faction=None))
    assert unknown[13][:2] == ["Hall of Thanes", "Ragefire Chasm"]
    later = ahead(level=27, levels=3)
    dalaran = next(e for g in later.groups for e in g.events if e.title == "City of Dalaran")
    assert dalaran.locked
    assert "Announced" not in str(titles(ahead(level=20, levels=1)))


def test_essential_quests_and_points_past_the_plan() -> None:
    view = ahead(level=29, levels=2)
    assert titles(view) == {
        30: ["Class quest: The Islander", "Talent point"],
        31: ["Talent point"],
    }
    islander, extra = view.groups[0].events
    assert islander.essential
    assert extra.detail == "Not in the plan yet"


def test_never_past_the_level_cap_or_without_a_level() -> None:
    assert [g.level for g in ahead(level=58, levels=10).groups] == [59, 60]
    assert ahead(level=None).groups == []


def test_the_look_ahead_api(client: TestClient, engine: Engine) -> None:  # noqa: F811
    assert client.get("/api/look-ahead").json() == {"level": None, "levels": 5, "groups": []}
    store_list(engine)
    for kind in ("profile", "professions"):
        snapshot = {"kind": kind, "payload": fixture(kind)}
        client.post("/api/snapshots/manual", json=snapshot)

    # The real profile is level 18: levels 19 and 20 ahead.
    view = client.get("/api/look-ahead", params={"levels": 2}).json()
    assert (view["level"], view["levels"]) == (18, 2)
    by_level = {g["level"]: [e["title"] for e in g["events"]] for g in view["groups"]}
    assert "Class quest: Yorus Barleybrew" in by_level[20]
    assert "Expert Engineering" in by_level[20]
    assert all(any(t.startswith("Talent") for t in titles) for titles in by_level.values())

    for bad in (0, 11):
        assert client.get("/api/look-ahead", params={"levels": bad}).status_code == 422
