"""A character's public page (#42, ADR 0063): opt-in, read-only, at an unguessable link."""

import json
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import public_page
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import Character, PublicPage, Snapshot
from character_planner.public_page import PublicCharacter
from character_planner.views import CharacterView

from .conftest import FIXTURES, api_client, tracked
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in, users_on  # noqa: F401

PAGE = "/api/character/public-page"
PUBLIC = "/api/public/character"
# Every field the page may show (#42): header, equipment, stats, professions, talents.
SHOWN = {
    "name",
    "surname",
    "level",
    "race",
    "character_class",
    "guild",
    "equipped_item_level",
    "gear_slots_filled",
    "captured_at",
    "stats",
    "professions",
    "specialization",
    "equipment",
}


def synced(engine: Engine) -> int:
    """The test character with a full sync stored, from the real Forever samples."""
    with Session(engine) as session:
        character_id = tracked(session)
        for kind in ("profile", "equipment", "statistics", "professions", "specializations"):
            payload = json.loads((FIXTURES / f"forever_{kind}.json").read_text(encoding="utf-8"))
            session.add(
                Snapshot(
                    character_id=character_id,
                    source="api",
                    kind=kind,
                    status=200,
                    payload=payload,
                )
            )
        session.commit()
        return character_id


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Any:
    synced(engine)
    with api_client(create_app(settings, engine)) as client:
        yield client


def test_the_public_model_names_only_the_shown_fields() -> None:
    assert set(PublicCharacter.model_fields) == SHOWN
    # What the owner's view has beyond it stays private: the addon's level, for one.
    assert set(CharacterView.model_fields) - SHOWN == {"level_source"}


def test_off_by_default(client: TestClient) -> None:
    assert client.get(PAGE).json() == {"enabled": False, "token": None, "created_at": None}


@respx.mock  # no routes: any call to Blizzard or Forever Companion fails the test
def test_on_shows_the_snapshot_to_anyone_with_the_link(
    client: TestClient, settings: Settings, engine: Engine
) -> None:
    turned_on = client.put(PAGE, json={"enabled": True}).json()
    token = turned_on["token"]
    assert turned_on["enabled"] is True
    assert len(token) == 32
    assert client.put(PAGE, json={"enabled": True}).json()["token"] == token  # unchanged

    with api_client(create_app(settings, engine)) as stranger:
        response = stranger.post(PUBLIC, json={"token": token})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    page = response.json()
    assert set(page) == SHOWN
    assert page["name"] == "Brumboldt"
    assert page["level"] is not None
    assert page["equipment"]
    assert not respx.calls  # read from the database only


def test_off_or_a_new_link_breaks_the_old_one(client: TestClient) -> None:
    first = client.put(PAGE, json={"enabled": True}).json()["token"]
    second = client.post(f"{PAGE}/regenerate").json()["token"]
    assert second != first
    assert client.post(PUBLIC, json={"token": first}).status_code == 404
    assert client.post(PUBLIC, json={"token": second}).status_code == 200

    assert client.put(PAGE, json={"enabled": False}).json()["enabled"] is False
    assert client.post(PUBLIC, json={"token": second}).status_code == 404
    assert client.post(f"{PAGE}/regenerate").status_code == 404  # nothing to replace
    # On again: a new link, never the old one.
    assert client.put(PAGE, json={"enabled": True}).json()["token"] not in (first, second)


@pytest.mark.parametrize("token", ["", "x", "a" * 31, "a" * 33, "../../etc/passwd" + "a" * 16])
def test_unknown_and_malformed_links_are_404(client: TestClient, token: str) -> None:
    client.put(PAGE, json={"enabled": True})
    assert client.post(PUBLIC, json={"token": token}).status_code in (404, 422)


def test_the_page_never_carries_private_data(client: TestClient, engine: Engine) -> None:
    """Plans, targets, weights, other characters and the addon's data stay out."""
    with Session(engine) as session:
        session.add(Character(region="eu", slug="secret-alt", name="Secretalt", surname="X"))
        session.commit()
    client.put("/api/weights", json={"weights": {"strength": 9.75}})  # a setting of the owner's
    token = client.put(PAGE, json={"enabled": True}).json()["token"]
    body = client.post(PUBLIC, json={"token": token}).text
    for private in ("Secretalt", "level_source", "9.75", token, "weights", "targets"):
        assert private not in body, private


def test_deleting_the_character_deletes_its_page(client: TestClient, engine: Engine) -> None:
    token = client.put(PAGE, json={"enabled": True}).json()["token"]
    assert client.delete("/api/character").status_code == 200
    assert client.post(PUBLIC, json={"token": token}).status_code == 404
    with Session(engine) as session:
        assert session.exec(select(PublicPage)).all() == []


def test_after_the_30_day_rule_the_page_has_nothing_to_show(
    client: TestClient, engine: Engine
) -> None:
    token = client.put(PAGE, json={"enabled": True}).json()["token"]
    with Session(engine) as session:
        for snapshot in session.exec(select(Snapshot)).all():
            session.delete(snapshot)
        session.commit()
    page = client.post(PUBLIC, json={"token": token}).json()
    assert page["name"] is None
    assert page["equipment"] == []


@respx.mock
def test_with_users_on_it_needs_no_sign_in_and_only_the_owner_controls_it(
    users_on: Settings,  # noqa: F811
    engine: Engine,
) -> None:
    mock_battle_net()
    synced(engine)
    app = create_app(users_on.model_copy(update={"planner_signups": True}), engine)
    with browser(app) as owner, browser(app) as other, browser(app) as visitor:
        sign_in(owner, ADMIN)
        sign_in(other, GUILDMATE)
        brumboldt = owner.get("/api/characters").json()["characters"][0]["id"]
        theirs = {"X-Character-Id": str(brumboldt)}
        assert other.put(PAGE, json={"enabled": True}, headers=theirs).status_code == 404
        assert other.get(PAGE, headers=theirs).status_code == 404
        token = owner.put(PAGE, json={"enabled": True}).json()["token"]
        assert visitor.get("/api/character").status_code == 401  # signed out
        page = visitor.post(PUBLIC, json={"token": token})
        assert page.status_code == 200
        assert page.json()["name"] == "Brumboldt"
        assert other.post(f"{PAGE}/regenerate", headers=theirs).status_code == 404


def test_the_view_is_built_from_the_owner_view() -> None:
    view = CharacterView(name="A", level=12)
    assert public_page.public_view(view).model_dump()["name"] == "A"
