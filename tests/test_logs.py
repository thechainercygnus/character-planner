import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from character_planner import jobs
from character_planner.app import create_app
from character_planner.blizzard import oauth
from character_planner.config import Settings
from character_planner.logs import (
    ACCESS_LOGGER,
    REDACTED,
    JobLog,
    JsonFormatter,
    RedactingFormatter,
    RequestIdFilter,
    configure_logging,
    redact,
    request_id,
    safe_database_url,
)

from .test_app import mock_character_api
from .test_dungeons import mock_companion_dungeons
from .test_items import mock_battlenet

# Made-up values: the tests check they never reach a log. Marked for the secret scanners.
TOKEN = "tok-SECRET-1234567890"  # gitleaks:allow ggignore
CODE = "CODE-SECRET-abcdef"  # gitleaks:allow ggignore


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """configure_logging changes global state: put pytest's handlers back afterwards."""
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    names = [ACCESS_LOGGER, "uvicorn", "uvicorn.error", "uvicorn.access", "httpx"]
    loggers = {
        n: (lg.level, list(lg.handlers), lg.propagate)
        for n in names
        if (lg := logging.getLogger(n))
    }
    yield
    for handler in root.handlers:
        if handler not in saved[1]:
            handler.close()
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    for name, (level, handlers, propagate) in loggers.items():
        lg = logging.getLogger(name)
        for handler in lg.handlers:
            if handler not in handlers:
                handler.close()
        lg.setLevel(level)
        lg.handlers[:] = handlers
        lg.propagate = propagate


# --- redaction ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Authorization: Bearer abc.DEF-123", "Authorization: Bearer "),
        ("GET /auth/callback?code=abc123&state=xyz", "GET /auth/callback?code="),
        ("POST token access_token=abc&expires_in=5", "&expires_in=5"),
        ('{"access_token": "abc", "expires_in": 5}', '"expires_in": 5'),
        ("client_secret=hunter2", "client_secret="),
        ("postgresql://planner:hunter2@db/planner", "postgresql://planner:"),
    ],
)
def test_secrets_are_redacted(text: str, kept: str) -> None:
    out = redact(text)
    assert REDACTED in out
    assert kept in out
    for secret in ("abc.DEF-123", "abc123", "xyz", "hunter2"):
        assert secret not in out


def test_ordinary_text_is_left_alone() -> None:
    text = "status_code=200 for item 5193, encode=utf-8, 3 errors"
    assert redact(text) == text


def test_known_secret_values_are_redacted_anywhere() -> None:
    assert redact("the secret is s3cr3t-value!", ("s3cr3t-value",)) == "the secret is [redacted]!"


def test_database_url_hides_the_password() -> None:
    assert safe_database_url("postgresql://planner:hunter2@db/planner") == (
        "postgresql://planner:***@db/planner"
    )
    for url in ("sqlite:///data/character-planner.db", "sqlite:///C:/Users/me/planner.db"):
        assert safe_database_url(url) == url


def _format(formatter: logging.Formatter, message: str, *args: object) -> str:
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, message, args, None)
    RequestIdFilter().filter(record)
    return formatter.format(record)


def test_formatters_redact_messages_and_tracebacks() -> None:
    text = RedactingFormatter("%(request_id)s %(message)s", secrets=("s3cr3t",))
    assert _format(text, "token %s and s3cr3t", f"Bearer {TOKEN}") == (
        "- token Bearer [redacted] and [redacted]"
    )
    try:
        raise RuntimeError(f"failed with access_token={TOKEN}")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    RequestIdFilter().filter(record)
    out = text.format(record)
    assert "RuntimeError" in out and TOKEN not in out


def test_json_lines_carry_the_request_id() -> None:
    reset = request_id.set("req-1")
    try:
        line = _format(JsonFormatter(secrets=()), "hello %s", "world")
    finally:
        request_id.reset(reset)
    entry = json.loads(line)
    assert (entry["message"], entry["request_id"], entry["level"]) == (
        "hello world",
        "req-1",
        "ERROR",
    )


# --- setup ------------------------------------------------------------------------------------


@pytest.mark.usefixtures("restore_logging")
def test_the_api_writes_server_and_access_logs(tmp_path: Path, settings: Settings) -> None:
    logs = tmp_path / "logs"
    configure_logging(settings.model_copy(update={"log_dir": logs}), "api")
    logging.getLogger("character_planner.jobs").info("a server line")
    logging.getLogger(ACCESS_LOGGER).info('127.0.0.1 "GET /api/gear" 200 3ms [abc]')
    for handler in logging.getLogger().handlers + logging.getLogger(ACCESS_LOGGER).handlers:
        handler.flush()

    server = (logs / "server.log").read_text(encoding="utf-8")
    access = (logs / "access.log").read_text(encoding="utf-8")
    assert "a server line" in server and "GET /api/gear" not in server
    assert "GET /api/gear" in access and "a server line" not in access


@pytest.mark.usefixtures("restore_logging")
def test_the_worker_writes_its_own_file(tmp_path: Path, settings: Settings) -> None:
    logs = tmp_path / "logs"
    configure_logging(settings.model_copy(update={"log_dir": logs}), "worker")
    logging.getLogger("character_planner.worker").info("sync: running")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "sync: running" in (logs / "worker.log").read_text(encoding="utf-8")
    assert not (logs / "server.log").exists()


@pytest.mark.usefixtures("restore_logging")
def test_upstream_requests_are_logged_only_at_debug(settings: Settings) -> None:
    configure_logging(settings, "api")
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    configure_logging(settings.model_copy(update={"log_level": "DEBUG"}), "api")
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.INFO


# --- requests ---------------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, engine)) as test_client:
        yield test_client


def test_each_request_gets_an_id_and_an_access_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        response = client.get("/api/gear?x=1")
    rid = response.headers["X-Request-ID"]
    assert len(rid) == 12
    (line,) = [r.getMessage() for r in caplog.records if r.name == ACCESS_LOGGER]
    assert '"GET /api/gear?x=1" 200' in line and rid in line

    assert (
        client.get("/api/gear", headers={"X-Request-ID": "proxy-42"}).headers["X-Request-ID"]
        == "proxy-42"
    )
    odd = client.get("/api/gear", headers={"X-Request-ID": "bad id\nwith newline"})
    assert odd.headers["X-Request-ID"] != "bad id\nwith newline"


def test_health_checks_stay_out_of_the_access_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        client.get("/api/healthz")
    assert [r for r in caplog.records if r.name == ACCESS_LOGGER] == []


def test_lines_a_request_causes_carry_its_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.INFO):
        response = client.post("/api/sync")  # not logged in
    assert response.status_code == 401
    (skipped,) = [r for r in caplog.records if "Sync skipped" in r.getMessage()]
    assert skipped.__dict__["request_id"] == response.headers["X-Request-ID"]


def test_an_unhandled_error_is_one_logged_line_and_a_500_with_the_id(
    client: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("pool exploded")

    monkeypatch.setattr(jobs, "refresh_item_pool", boom)
    with caplog.at_level(logging.INFO):
        response = client.post("/api/pool/refresh")
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": response.headers["X-Request-ID"],
    }
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "POST /api/pool/refresh" in errors[0].getMessage() and errors[0].exc_info


# --- jobs -------------------------------------------------------------------------------------


def test_job_log_reports_start_progress_end_and_errors(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("character_planner.test")
    with caplog.at_level(logging.INFO, logger="character_planner.test"):
        job = JobLog(log, "Things", 120, every=50)
        for index in range(1, 121):
            job.step(index)
        job.done("120 fetched", [f"item {n}: HTTP 500" for n in range(25)])
    messages = [r.getMessage() for r in caplog.records]
    assert messages[:3] == ["Things: 120 to fetch", "Things: 50/120 done", "Things: 100/120 done"]
    assert messages[3].startswith("Things: done in ") and messages[3].endswith("120 fetched")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 21  # 20 listed, then a count
    assert warnings[-1].getMessage() == "Things: 5 more errors"


@respx.mock
def test_a_pool_refresh_without_a_character_says_it_fetches_the_whole_pool(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    mock_companion_dungeons()
    respx.get(url__startswith="https://forevercompanion.io/api/v1/items/").mock(
        return_value=httpx.Response(404, json={})
    )
    with caplog.at_level(logging.INFO):
        client.post("/api/pool/refresh")
    messages = [r.getMessage() for r in caplog.records]
    assert any("no character level, so fetching details for the whole pool" in m for m in messages)
    assert any(m.startswith("Forever Companion dungeons (2 listed): 2 to fetch") for m in messages)
    assert any(m.startswith("Forever Companion items: ") and "to fetch" in m for m in messages)
    assert any(m.startswith("Item pool refresh: done in ") for m in messages)


@respx.mock
@pytest.mark.usefixtures("restore_logging")
def test_no_token_code_or_secret_reaches_the_log_files(
    tmp_path: Path, settings: Settings, engine: Engine
) -> None:
    logs = tmp_path / "logs"
    settings = settings.model_copy(
        update={
            "log_dir": logs,
            "log_level": "DEBUG",
            "bnet_client_secret": SecretStr("client-SECRET-xyz"),
        }
    )
    configure_logging(settings, "api")
    with TestClient(create_app(settings, engine)) as client:
        login = client.get("/auth/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        respx.post(oauth.TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": TOKEN, "expires_in": 86399})
        )
        client.get(f"/auth/callback?code={CODE}&state={state}", follow_redirects=False)
        mock_character_api()
        mock_battlenet()
        client.post("/api/sync")
        logging.getLogger("character_planner.test").warning(
            "a careless line: Bearer %s client_secret=%s", TOKEN, "client-SECRET-xyz"
        )
    for handler in logging.getLogger().handlers + logging.getLogger(ACCESS_LOGGER).handlers:
        handler.flush()

    written = "".join(p.read_text(encoding="utf-8") for p in logs.glob("*.log"))
    assert "/auth/callback?code=[redacted]" in written  # the access line is there...
    assert "Sync brumboldt-doomlet: started" in written
    for secret in (TOKEN, CODE, state, "client-SECRET-xyz"):
        assert secret not in written  # ...but never a secret
