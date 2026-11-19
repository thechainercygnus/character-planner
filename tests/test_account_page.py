"""The account page (#217, ADR 0058): one user's characters and data, and the self-service
export. With users on, each user sees only their own; without, the one person sees all."""

import io
import json
import zipfile

import respx
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import GuildMembership

from .test_app import client, mock_character_api  # noqa: F401 (the client fixture)
from .test_data_requests import give_character, open_app, user_id
from .test_items import mock_battlenet
from .test_notify import HOOK_TOKEN, OTHER
from .test_own_webhooks import add_hook
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in


@respx.mock
def test_without_users_the_page_lists_every_character_and_no_account(client: TestClient) -> None:  # noqa: F811
    mock_character_api()
    mock_battlenet()
    client.post("/api/sync")
    view = client.get("/api/account").json()
    assert (view["users"], view["account_id"], view["role"]) == (False, None, None)
    (brumboldt,) = view["characters"]
    assert brumboldt["name"] == "Brumboldt Doomlet" and brumboldt["default"]
    assert brumboldt["level"] == 18 and brumboldt["last_sync"] is not None
    assert brumboldt["guild"] == "Daves Discount Meats"  # from its profile
    assert (brumboldt["in_guild_view"], brumboldt["game_data_at"]) == (False, None)

    exported = client.get("/api/account/export")
    assert exported.status_code == 200
    assert 'filename="character-planner-everything-' in exported.headers["content-disposition"]
    names = set(zipfile.ZipFile(io.BytesIO(exported.content)).namelist())
    assert "account.json" not in names  # there's no account
    assert "characters/us-brumboldt-doomlet/snapshot.json" in names


def test_the_guild_view_shows_on_the_page(settings: Settings, engine: Engine) -> None:
    with TestClient(create_app(settings, engine)) as fresh:
        fresh.get("/api/characters")  # seeds the character from the settings
        character_id = fresh.get("/api/account").json()["characters"][0]["id"]
        with Session(engine) as session:
            session.add(
                GuildMembership(
                    character_id=character_id, region="us", guild_id=1, guild_name="Guild"
                )
            )
            session.commit()
        assert fresh.get("/api/account").json()["characters"][0]["in_guild_view"] is True


@respx.mock
def test_each_user_sees_and_exports_only_their_own(settings: Settings, engine: Engine) -> None:
    mock_battle_net()
    users_on = settings.model_copy(update={"planner_users": True})
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        give_character(engine, GUILDMATE)
        add_hook(guildmate, OTHER)

        mine = guildmate.get("/api/account").json()
        assert (mine["users"], mine["account_id"], mine["role"]) == (True, GUILDMATE, "user")
        assert [c["name"] for c in mine["characters"]] == ["Lilalx"]
        assert mine["characters"][0]["default"] is True
        theirs = admin.get("/api/account").json()
        assert [c["name"] for c in theirs["characters"]] == ["Brumboldt Doomlet"]

        exported = guildmate.get("/api/account/export")
        assert (
            f'filename="character-planner-{GUILDMATE}-' in exported.headers["content-disposition"]
        )
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert json.loads(archive.read("account.json"))["account_id"] == GUILDMATE
        folders = {n.split("/")[1] for n in archive.namelist() if n.startswith("characters/")}
        assert folders == {"eu-lilalx"}  # nothing of the admin's
        assert HOOK_TOKEN not in b"".join(archive.read(n) for n in archive.namelist()).decode()
    assert user_id(engine, GUILDMATE)  # the export deleted nothing
