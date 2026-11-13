"""The app's own Battle.net token, and syncs that need no login (#107, ADR 0027).

Every request is mocked with respx: no test reaches Battle.net.
"""

import logging
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from character_planner import jobs, worker
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.db import Snapshot, StoredToken
from character_planner.tokens import (
    APP_TOKEN_ID,
    RENEW_BEFORE,
    CredentialsError,
    app_token,
    cached_app_token,
)

from .test_app import BASE, fixture

SECRET_TOKEN = "app-token-never-logged"


def token_response(token: str = SECRET_TOKEN, expires_in: int = 86399) -> httpx.Response:
    return httpx.Response(200, json={"access_token": token, "expires_in": expires_in})


def store(engine: Engine, row_id: int, token: str, expires_in: float) -> None:
    with Session(engine) as session:
        session.merge(
            StoredToken(id=row_id, access_token=token, expires_at=time.time() + expires_in)
        )
        session.commit()


def mock_character(token_status: dict[str, int] | None = None, profile: int = 200) -> None:
    """The character endpoints a sync calls. token_status maps a bearer token to the
    status every endpoint answers it with (401 for a token Blizzard no longer takes)."""
    token_status = token_status or {}

    def answer(kind: str, ok_status: int):
        def respond(request: httpx.Request) -> httpx.Response:
            bearer = request.headers["Authorization"].removeprefix("Bearer ")
            status = token_status.get(bearer, ok_status)
            if status != 200:
                return httpx.Response(status, json={"code": status})
            return httpx.Response(200, json=fixture(kind))

        return respond

    respx.get(BASE).mock(side_effect=answer("profile", profile))
    for kind in ("equipment", "statistics", "professions", "specializations"):
        respx.get(f"{BASE}/{kind}").mock(side_effect=answer(kind, profile))
    respx.get(url__startswith=f"{BASE}/").mock(return_value=httpx.Response(404, text="Not Found"))
    # The item lookups that follow a sync: nothing found, which is fine here.
    respx.route(host="us.api.blizzard.com").mock(return_value=httpx.Response(404, json={}))
    respx.route(host="forevercompanion.io").mock(return_value=httpx.Response(404, json={}))


# --- the token ---------------------------------------------------------------------------


@respx.mock
def test_the_app_token_is_fetched_once_and_cached(engine: Engine, settings: Settings) -> None:
    route = respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    with Session(engine) as session:
        first = app_token(session, settings)
        second = app_token(session, settings)
        assert session.get(StoredToken, 1) is None  # the login's row is untouched
        stored = session.get(StoredToken, APP_TOKEN_ID)
    assert route.call_count == 1
    assert first == second and first.access_token == SECRET_TOKEN
    assert stored is not None and stored.access_token == SECRET_TOKEN


@respx.mock
def test_a_token_close_to_expiry_is_replaced_early(engine: Engine, settings: Settings) -> None:
    store(engine, APP_TOKEN_ID, "old", RENEW_BEFORE - 60)
    route = respx.post(oauth.TOKEN_URL).mock(return_value=token_response("new"))
    with Session(engine) as session:
        assert cached_app_token(session) is None
        assert app_token(session, settings).access_token == "new"
    assert route.call_count == 1


@respx.mock
def test_renew_replaces_a_token_that_has_not_expired(engine: Engine, settings: Settings) -> None:
    store(engine, APP_TOKEN_ID, "old", 3600)
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response("new"))
    with Session(engine) as session:
        assert app_token(session, settings).access_token == "old"
        assert app_token(session, settings, renew=True).access_token == "new"
        assert app_token(session, settings).access_token == "new"


@respx.mock  # no routes: a request would fail the test
def test_no_client_means_no_request(engine: Engine, settings: Settings) -> None:
    missing = settings.model_copy(update={"bnet_client_id": ""})
    with Session(engine) as session, pytest.raises(CredentialsError, match="aren't set"):
        app_token(session, missing)


@pytest.mark.parametrize("status", [400, 401])
@respx.mock
def test_a_refused_client_is_a_credentials_error(
    engine: Engine, settings: Settings, status: int
) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(status, json={}))
    with Session(engine) as session, pytest.raises(CredentialsError) as error:
        app_token(session, settings)
    assert f"HTTP {status}" in str(error.value)
    assert "test-secret" not in str(error.value)


@respx.mock
def test_battle_net_being_down_is_not_a_credentials_error(
    engine: Engine, settings: Settings
) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(503, text="down"))
    with Session(engine) as session, pytest.raises(httpx.HTTPStatusError):
        app_token(session, settings)


@respx.mock
def test_concurrent_callers_share_one_new_token(engine: Engine, settings: Settings) -> None:
    def slow_token(_request: httpx.Request) -> httpx.Response:
        time.sleep(0.2)  # long enough for every thread to be waiting
        return token_response()

    route = respx.post(oauth.TOKEN_URL).mock(side_effect=slow_token)
    tokens: list[str] = []

    def call() -> None:
        with Session(engine) as session:
            tokens.append(app_token(session, settings).access_token)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert tokens == [SECRET_TOKEN] * 5
    assert route.call_count == 1


@respx.mock
def test_tokens_are_never_logged(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character()
    with caplog.at_level(logging.DEBUG), Session(engine) as session:
        app_token(session, settings, renew=True)
        jobs.sync_character(session, settings)
    assert caplog.records  # something was logged
    assert all(SECRET_TOKEN not in record.getMessage() for record in caplog.records)


# --- syncs without a login ------------------------------------------------------------------


@respx.mock
def test_a_sync_needs_no_login(engine: Engine, settings: Settings) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character()
    with Session(engine) as session:
        assert session.get(StoredToken, 1) is None  # never logged in
        statuses = jobs.sync_character(session, settings)
        kinds = {s.kind for s in session.exec(select(Snapshot)).all()}
    assert statuses["profile"] == 200
    assert {"profile", "equipment", "statistics", "professions", "specializations"} <= kinds
    calls = [c.request for c in respx.calls if c.request.url.path.startswith("/profile/wow")]
    assert calls and all(c.headers["Authorization"] == f"Bearer {SECRET_TOKEN}" for c in calls)


@respx.mock
def test_a_401_gets_a_new_token_and_one_retry(engine: Engine, settings: Settings) -> None:
    store(engine, APP_TOKEN_ID, "revoked", 3600)  # cached, not expired, but refused
    token = respx.post(oauth.TOKEN_URL).mock(return_value=token_response("fresh"))
    mock_character(token_status={"revoked": 401})
    with Session(engine) as session:
        statuses = jobs.sync_character(session, settings)
        statuses_stored = {s.status for s in session.exec(select(Snapshot)).all()}
    assert token.call_count == 1
    assert statuses["profile"] == 200
    assert 401 not in statuses_stored  # the refused attempt isn't kept as data


@respx.mock
def test_a_second_401_means_the_client_is_refused(engine: Engine, settings: Settings) -> None:
    respx.post(oauth.TOKEN_URL).mock(side_effect=[token_response("a"), token_response("b")])
    mock_character(token_status={"a": 401, "b": 401})
    with Session(engine) as session:
        with pytest.raises(CredentialsError, match="refused a new app token too"):
            jobs.sync_character(session, settings)
        assert session.exec(select(Snapshot)).all() == []


@respx.mock
def test_other_failures_are_stored_not_retried(engine: Engine, settings: Settings) -> None:
    token = respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character(profile=503)
    with Session(engine) as session:
        statuses = jobs.sync_character(session, settings)
    assert statuses["profile"] == 503
    assert token.call_count == 1  # no renewal for a server error


# --- the worker ----------------------------------------------------------------------------


@respx.mock  # no routes: a request would fail the test
def test_the_worker_skips_syncs_without_a_client(engine: Engine, settings: Settings) -> None:
    missing = settings.model_copy(update={"bnet_client_secret": SecretStr("")})
    with Session(engine) as session:
        assert worker.sync_job(session, missing, None).startswith("skipped: no Battle.net client")


@respx.mock
def test_the_worker_syncs_without_a_login(engine: Engine, settings: Settings) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character()
    with Session(engine) as session:
        assert worker.sync_job(session, settings, None).startswith("synced 7 endpoints")


@respx.mock
def test_the_worker_names_a_character_it_cannot_find(engine: Engine, settings: Settings) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character(profile=404)
    with Session(engine) as session:
        outcome = worker.sync_job(session, settings, None)
    assert outcome == "character brumboldt-doomlet not found: check its name and region"


@respx.mock
def test_a_refused_client_fails_the_job_and_alerts(engine: Engine, settings: Settings) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(401, json={}))
    schedule = worker.Schedule(jobs=[worker.Job("sync", worker.RETRY_SKIPPED, worker.sync_job)])
    outcomes = worker.run_due(engine, settings, schedule, worker.utcnow())
    assert outcomes["sync"].startswith("failed: CredentialsError: Battle.net refused the client")


# --- the API -------------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


@respx.mock
def test_sync_now_works_without_a_login(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character()
    before = client.get("/api/status").json()
    assert (before["can_sync"], before["character_found"], before["logged_in"]) == (
        True,
        None,
        False,
    )
    assert client.post("/api/sync").json()["profile"] == 200
    assert client.get("/api/status").json()["character_found"] is True


@respx.mock
def test_sync_now_says_when_the_client_is_refused(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(401, json={}))
    response = client.post("/api/sync")
    assert response.status_code == 503
    assert "check BNET_CLIENT_ID and BNET_CLIENT_SECRET" in response.json()["detail"]


@respx.mock
def test_status_says_when_the_character_was_not_found(client: TestClient) -> None:
    respx.post(oauth.TOKEN_URL).mock(return_value=token_response())
    mock_character(profile=404)
    client.post("/api/sync")
    assert client.get("/api/status").json()["character_found"] is False


def test_status_says_when_there_is_no_client(settings: Settings, engine: Engine) -> None:
    missing = settings.model_copy(update={"bnet_client_id": ""})
    with TestClient(create_app(missing, engine)) as client:
        assert client.get("/api/status").json()["can_sync"] is False
