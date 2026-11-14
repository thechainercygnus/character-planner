"""Characters as records (#14, ADR 0036): seeded once from .env, owning their data, and
never mixed up with each other."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import respx
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.characters import current_character, first_character
from character_planner.config import Settings
from character_planner.db import Character, ProgressHistory, Snapshot, latest_by_kind
from character_planner.progress import progress
from character_planner.retention import forget_character
from character_planner.scoring import Weights

from .conftest import api_client, tracked, tracked_character
from .test_app import fixture, mock_character_api

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def add_profile(session: Session, character_id: int, level: int, at: datetime = T0) -> None:
    payload = {"level": level, "name": "X", "character_class": {"name": "Warrior"}}
    session.add(
        Snapshot(
            character_id=character_id,
            source="api",
            kind="profile",
            status=200,
            payload=payload,
            captured_at=at,
        )
    )
    session.commit()


def alt(session: Session) -> int:
    """A second character on the same instance."""
    other = Character(region="eu", slug="someone-else", name="Someone", surname="Else")
    session.add(other)
    session.commit()
    assert other.id is not None
    return other.id


def test_the_first_character_is_seeded_from_settings_and_adopts_old_rows(
    engine: Engine, settings: Settings
) -> None:
    with Session(engine) as session:
        # Rows from before #14 have no character.
        session.add(Snapshot(source="api", kind="profile", status=200, payload={"level": 17}))
        session.add(ProgressHistory(captured_at=T0 - timedelta(days=40), level=12))
        session.commit()

        character = current_character(session, settings)
        assert character is not None
        assert (character.region, character.slug, character.name, character.surname) == (
            "us",
            "brumboldt-doomlet",
            "Brumboldt",
            "Doomlet",
        )
        assert {s.character_id for s in session.exec(select(Snapshot)).all()} == {character.id}
        assert {h.character_id for h in session.exec(select(ProgressHistory)).all()} == {
            character.id
        }


def test_settings_are_not_read_once_a_character_exists(engine: Engine, settings: Settings) -> None:
    """.env names the first character only (ADR 0036): later edits don't swap it."""
    with Session(engine) as session:
        first = current_character(session, settings)
        renamed = settings.model_copy(update={"character_name": "Other"})
        again = current_character(session, renamed)
        assert first is not None and again is not None and again.id == first.id
        assert len(session.exec(select(Character)).all()) == 1


def test_without_a_name_there_is_no_character(engine: Engine, settings: Settings) -> None:
    unnamed = settings.model_copy(update={"character_name": ""})
    with Session(engine) as session:
        assert current_character(session, unnamed) is None
        assert latest_by_kind(session, None) == {}
    with api_client(create_app(unnamed, engine)) as client:
        assert client.get("/api/character").json()["level"] is None
        assert client.post("/api/sync").status_code == 409


def test_two_characters_never_see_each_others_data(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        me, other = tracked(session), alt(session)
        add_profile(session, me, 18)
        add_profile(session, other, 42)
        session.add(ProgressHistory(character_id=other, captured_at=T0 - timedelta(days=60)))
        session.commit()

        assert latest_by_kind(session, me)["profile"].payload["level"] == 18
        assert latest_by_kind(session, other)["profile"].payload["level"] == 42
        mine = progress(session, Weights(weights={}), me)
        assert [p.level for p in mine.points] == [18]  # not the alt's 42, nor its history
        assert jobs.character_context(session, other)[0] == 42

    # The app shows the current character (the first) and only its data.
    with api_client(create_app(settings, engine)) as client:
        assert client.get("/api/character").json()["level"] == 18
        assert [p["level"] for p in client.get("/api/progress").json()["points"]] == [18]


@respx.mock
def test_a_sync_stores_rows_for_its_character_and_copies_the_profile(
    engine: Engine, settings: Settings
) -> None:
    mock_character_api()
    respx.post(oauth.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 86399})
    )
    respx.route().mock(return_value=httpx.Response(404, json={"error": "Not found"}))
    profile = cast(dict[str, Any], fixture("profile"))
    with Session(engine) as session, httpx.Client() as http:
        me, other = tracked_character(session), alt(session)
        jobs.sync_character(session, settings, me, http=http)
        owners = {s.character_id for s in session.exec(select(Snapshot)).all()}
        session.refresh(me)
        assert owners == {me.id}
        assert latest_by_kind(session, other) == {}
        assert me.blizzard_id == profile["id"]
        assert me.character_class == profile["character_class"]["name"]
        assert me.race == profile["race"]["name"]
        assert me.faction == profile["faction"]["type"]


def test_forgetting_a_character_leaves_the_others_alone(engine: Engine) -> None:
    with Session(engine) as session:
        me = tracked_character(session)
        other = alt(session)
        payload = {"name": "Brumboldt", "surname": "Doomlet", "level": 18}
        for owner in (me.id, other):
            assert owner is not None
            session.add(
                Snapshot(
                    character_id=owner, source="api", kind="profile", status=200, payload=payload
                )
            )
            session.add(ProgressHistory(character_id=owner, captured_at=T0, level=10))
        session.commit()

        assert forget_character(session, me) == 2  # its snapshot and history only
        left = session.exec(select(Snapshot)).all()
        assert [s.character_id for s in left] == [other]
        assert [h.character_id for h in session.exec(select(ProgressHistory)).all()] == [other]
        assert first_character(session) is not None  # the record stays; its data went


# --- settings belong to a character (#14 step 2) ------------------------------------------


def test_each_character_keeps_its_own_settings(engine: Engine, settings: Settings) -> None:
    from character_planner.choices import set_choice, stored_choices
    from character_planner.class_quests import done_ids, set_done
    from character_planner.classes import load_class_defaults
    from character_planner.db import ClassQuestDone, CompanionClassQuest
    from character_planner.rules import current_rules, save_rules
    from character_planner.scoring import activate, active_key, current_weights
    from character_planner.talents import TalentPlan, current_plan, save_plan
    from character_planner.targets import current_targets, save_targets

    defaults = load_class_defaults(settings.curated_dir, "warrior")
    with Session(engine) as session:
        me, other = tracked(session), alt(session)
        session.add(CompanionClassQuest(quest_id="warrior-defensive-stance", payload={}))
        session.commit()

        save_rules(session, defaults.rules.model_copy(update={"per_slot": 1}), me)
        save_targets(session, defaults.targets.model_copy(update={"targets": []}), me)
        save_plan(session, TalentPlan(spec="Arms", steps=[]), me)
        activate(session, defaults.presets, "solo-dps", me)
        set_choice(session, 7, "Worn Axe", "dismissed", me)
        set_done(session, "warrior-defensive-stance", True, me)

        assert current_rules(session, defaults.rules, me).per_slot == 1
        assert current_rules(session, defaults.rules, other) == defaults.rules
        assert current_targets(session, defaults.targets, other) == defaults.targets
        assert current_plan(session, defaults.talent_plan, other) == defaults.talent_plan
        assert active_key(session, defaults.presets, me) == "solo-dps"
        assert active_key(session, defaults.presets, other) == defaults.presets.presets[0].key
        assert current_weights(session, defaults.presets, me) != current_weights(
            session, defaults.presets, other
        )
        assert stored_choices(session, me).dismissed == {7}
        assert stored_choices(session, other).dismissed == set()
        assert done_ids(session, me) == {"warrior-defensive-stance"}
        assert done_ids(session, other) == set()
        # The same quest can be done by both: the key is per character.
        set_done(session, "warrior-defensive-stance", True, other)
        assert len(session.exec(select(ClassQuestDone)).all()) == 2


def test_settings_from_before_characters_go_to_the_first(
    engine: Engine, settings: Settings
) -> None:
    from character_planner.db import ActiveWeightPreset, ItemChoice, StoredUsageRules

    with Session(engine) as session:
        session.add(StoredUsageRules(rules={"per_slot": 1}))
        session.add(ActiveWeightPreset(key="solo-dps"))
        session.add(ItemChoice(item_id=7, choice="dismissed", name="Worn Axe"))
        session.commit()
        character = current_character(session, settings)
        assert character is not None
        for model in (StoredUsageRules, ActiveWeightPreset, ItemChoice):
            assert [row.character_id for row in session.exec(select(model)).all()] == [character.id]


def test_settings_need_a_character(engine: Engine, settings: Settings) -> None:
    unnamed = settings.model_copy(update={"character_name": ""})
    with api_client(create_app(unnamed, engine)) as client:
        rules = client.get("/api/rules").json()
        assert client.put("/api/rules", json=rules["rules"]).status_code == 409
        assert client.put("/api/weights/active", json={"key": "solo-dps"}).status_code == 409


def test_rows_without_an_owner_are_adopted_at_start(engine: Engine, settings: Settings) -> None:
    """After a downgrade past 0010 and an upgrade, characters exist but settings come
    back without one: the next start gives them to the first character."""
    from character_planner.db import StoredUsageRules

    with Session(engine) as session:
        me = tracked(session)
        session.add(StoredUsageRules(rules={"per_slot": 1}))
        session.commit()
    with api_client(create_app(settings, engine)):
        pass
    with Session(engine) as session:
        (rules,) = session.exec(select(StoredUsageRules)).all()
        assert rules.character_id == me
