"""Backups (#240, ADR 0061): a logical dump without Blizzard's data, encrypted with age,
uploaded to S3-compatible storage (moto stands in for it), pruned to BACKUP_KEEP, and
restored into an empty database."""

import gzip
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import boto3
import pyrage
import pytest
import respx
from moto import mock_aws
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from character_planner import backup, dbcli, retention
from character_planner.app import create_app
from character_planner.config import Settings
from character_planner.db import (
    CatalogItem,
    Character,
    ItemChoice,
    Snapshot,
    StoredToken,
    current_revision,
    make_engine,
    utcnow,
)

from .conftest import tracked
from .test_cli import cli_settings  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_data_requests import open_app, user_id
from .test_users import ADMIN, GUILDMATE, browser, mock_battle_net, sign_in

BUCKET = "planner-backups"
IDENTITY = pyrage.x25519.Identity.generate()


@pytest.fixture
def configured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "backup_s3_bucket": BUCKET,
            "backup_s3_key_id": "test-key",
            "backup_s3_secret": SecretStr("test-secret"),
            "backup_age_recipient": str(IDENTITY.to_public()),
            "backup_keep": 2,
        }
    )


@pytest.fixture
def s3() -> Iterator[object]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def seed(engine: Engine) -> int:
    """Something people made, and some of Blizzard's data."""
    with Session(engine) as session:
        character_id = tracked(session)
        session.add(
            Snapshot(
                character_id=character_id,
                source="api",
                kind="profile",
                status=200,
                payload={"level": 19},
            )
        )
        session.add(
            Snapshot(
                character_id=character_id,
                source="manual",
                kind="equipment",
                status=200,
                payload={"mine": 1},
            )
        )
        session.add(
            ItemChoice(character_id=character_id, item_id=5193, name="Cape", choice="dismissed")
        )
        session.add(CatalogItem(name_key="cape", name="Cape", found=False))
        session.add(StoredToken(id=1, access_token="secret-token", expires_at=0, scope=""))
        session.commit()
        return character_id


def test_every_left_out_table_exists_and_blizzards_caches_are_left_out() -> None:
    tables = {t.name for t in SQLModel.metadata.sorted_tables}
    assert set(backup.EXCLUDED) <= tables  # no stale names
    assert {name for name, _, _ in retention.CACHES} <= set(backup.EXCLUDED)
    assert {"storedtoken", "usertoken", "usersession"} <= set(backup.EXCLUDED)
    kept = {t.name for t in backup.backed_up()}
    assert {"user", "character", "snapshot", "itemchoice", "role", "adminaction"} <= kept


def test_a_dump_leaves_out_blizzards_data_and_secrets(engine: Engine) -> None:
    seed(engine)
    document = json.loads(gzip.decompress(backup.dump(engine, "0.8.0")))
    assert document["format"] == backup.FORMAT and document["app_version"] == "0.8.0"
    assert document["revision"] == current_revision(engine)
    tables = document["tables"]
    assert [s["source"] for s in tables["snapshot"]] == ["manual"]  # Battle.net's left out
    assert "catalogitem" not in tables and "storedtoken" not in tables
    assert [c["name"] for c in tables["itemchoice"]] == ["Cape"]
    assert "secret-token" not in json.dumps(tables)


def test_a_backup_restores_into_an_empty_database(engine: Engine, tmp_path: Path) -> None:
    character_id = seed(engine)
    sealed = backup.encrypt(backup.dump(engine, "0.8.0"), str(IDENTITY.to_public()))
    assert b"Cape" not in sealed  # encrypted
    target = make_engine(f"sqlite:///{tmp_path / 'restored.db'}")
    try:
        restored = backup.restore(target, backup.decrypt(sealed, str(IDENTITY)))
        assert restored["itemchoice"] == 1 and restored["snapshot"] == 1
        assert current_revision(target) == current_revision(engine)  # at the newest migration
        with Session(target) as session:
            character = session.get(Character, character_id)
            assert character is not None and character.slug == "brumboldt-doomlet"
            choice = session.exec(select(ItemChoice)).one()
            assert choice.created_at is not None  # datetimes come back as datetimes
            assert session.exec(select(CatalogItem)).first() is None
        # Restoring again: the database isn't empty any more.
        with pytest.raises(backup.NotEmpty):
            backup.restore(target, backup.decrypt(sealed, str(IDENTITY)))
    finally:
        target.dispose()


def test_a_backup_from_another_schema_is_refused(engine: Engine, tmp_path: Path) -> None:
    document = json.loads(gzip.decompress(backup.dump(engine, "0.6.0")))
    document["revision"] = "0017"
    target = make_engine(f"sqlite:///{tmp_path / 'other.db'}")
    try:
        with pytest.raises(backup.WrongRevision, match=r"Restore it with planner 0.6.0"):
            backup.restore(target, gzip.compress(json.dumps(document).encode()))
    finally:
        target.dispose()


def test_only_the_private_key_decrypts() -> None:
    sealed = backup.encrypt(b"data", str(IDENTITY.to_public()))
    with pytest.raises(pyrage.DecryptError):
        backup.decrypt(sealed, str(pyrage.x25519.Identity.generate()))


@pytest.mark.usefixtures("s3")
def test_backups_upload_and_keep_the_newest(engine: Engine, configured: Settings) -> None:
    seed(engine)
    now = utcnow()
    with Session(engine) as session:
        for hours in (2, 1, 0):
            result = backup.run_backup(
                session, configured, "0.8.0", now=now - timedelta(hours=hours)
            )
        assert result.ok and result.kept == 2 and (result.rows or 0) > 0
        stored = backup.status(session)
    assert stored is not None and stored.key == result.key
    client = boto3.client("s3", region_name="us-east-1")
    keys = [o.get("Key", "") for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]
    assert len(keys) == 2 and result.key in keys  # the oldest pruned
    assert all(k.startswith("character-planner/") and k.endswith(backup.SUFFIX) for k in keys)
    body = client.get_object(Bucket=BUCKET, Key=keys[-1])["Body"].read()
    document = json.loads(gzip.decompress(backup.decrypt(body, str(IDENTITY))))
    assert document["app_version"] == "0.8.0"


@pytest.mark.usefixtures("s3")
def test_a_failed_backup_is_recorded_and_raised(engine: Engine, configured: Settings) -> None:
    missing = configured.model_copy(update={"backup_s3_bucket": "no-such-bucket"})
    with Session(engine) as session:
        with pytest.raises(Exception, match="NoSuchBucket"):
            backup.run_backup(session, missing, "0.8.0")
        stored = backup.status(session)
    assert stored is not None and not stored.ok and "NoSuchBucket" in (stored.error or "")


def test_a_backup_is_due_after_its_interval(engine: Engine, configured: Settings) -> None:
    with Session(engine) as session:
        assert backup.due(session, configured)  # never made
        backup._save(session, backup.BackupStatus(at=utcnow(), ok=True))  # pyright: ignore[reportPrivateUsage]
        assert not backup.due(session, configured)
        later = utcnow() + timedelta(hours=configured.backup_every_hours)
        assert backup.due(session, configured, later)
        backup._save(session, backup.BackupStatus(at=utcnow(), ok=False, error="x"))  # pyright: ignore[reportPrivateUsage]
        assert backup.due(session, configured)  # a failure tries again


@pytest.mark.usefixtures("s3")
def test_the_worker_backs_up_when_due(
    engine: Engine, settings: Settings, configured: Settings
) -> None:
    from character_planner import worker

    with Session(engine) as session:
        assert worker.backup_job(session, settings, None).startswith("skipped")
        assert worker.backup_job(session, configured, None).startswith("backed up")
        assert worker.backup_job(session, configured, None) == "not due"


def test_the_settings_take_only_a_public_key_and_https(settings: Settings) -> None:
    fields = settings.model_dump()
    with pytest.raises(ValidationError, match="never the secret key"):
        Settings.model_validate(fields | {"backup_age_recipient": str(IDENTITY)})
    with pytest.raises(ValidationError, match="https"):
        Settings.model_validate(fields | {"backup_s3_endpoint": "http://example.com"})
    with pytest.raises(ValidationError, match="1 or more"):
        Settings.model_validate(fields | {"backup_keep": 0})
    assert not settings.backups


@respx.mock
@pytest.mark.usefixtures("s3")
def test_the_admin_backs_up_from_the_admin_area(engine: Engine, configured: Settings) -> None:
    mock_battle_net()
    users_on = configured.model_copy(update={"planner_users": True})
    app = open_app(users_on, engine)
    with browser(app) as admin, browser(app) as guildmate:
        sign_in(admin, ADMIN)
        sign_in(guildmate, GUILDMATE)
        before = admin.get("/api/admin/backups").json()
        assert before["configured"] and before["last"] is None and before["keep"] == 2
        after = admin.post("/api/admin/backups").json()
        assert after["last"]["ok"] and after["last"]["key"].endswith(backup.SUFFIX)
        assert guildmate.get("/api/admin/backups").status_code == 403
        theirs = user_id(engine, GUILDMATE)
        admin.put(f"/api/admin/users/{theirs}/role", json={"role": "superuser"})
        assert guildmate.post("/api/admin/backups").status_code == 403  # the admin's alone


@respx.mock
def test_without_settings_there_is_nothing_to_back_up(engine: Engine, settings: Settings) -> None:
    mock_battle_net()
    app = create_app(settings.model_copy(update={"planner_users": True}), engine)
    with browser(app) as admin:
        sign_in(admin, ADMIN)
        assert admin.get("/api/admin/backups").json()["configured"] is False
        assert admin.post("/api/admin/backups").status_code == 409


def test_the_command_line_restores_an_encrypted_or_decrypted_file(
    engine: Engine,
    cli_settings: Settings,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(engine)
    gz = backup.dump(engine, "0.8.0")
    (tmp_path / "b.age").write_bytes(backup.encrypt(gz, str(IDENTITY.to_public())))
    (tmp_path / "key.txt").write_text(str(IDENTITY) + "\n")
    (tmp_path / "b.json.gz").write_bytes(gz)
    assert dbcli.main(["restore"]) == 2  # needs --file
    assert dbcli.main(["restore", "--file", str(tmp_path / "b.age")]) == 2  # needs --yes

    for name, extra in (("one", ["--identity", str(tmp_path / "key.txt")]), ("two", [])):
        target = f"sqlite:///{tmp_path / name}.db"
        monkeypatch.setattr(
            dbcli,
            "get_settings",
            lambda url=target: cli_settings.model_copy(update={"database_url": url}),
        )
        file = "b.age" if extra else "b.json.gz"
        assert dbcli.main(["restore", "--file", str(tmp_path / file), *extra, "--yes"]) == 0
        assert "Restored" in capsys.readouterr().out
    # Into a database that has data: refused, nothing written.
    assert dbcli.main(["restore", "--file", str(tmp_path / "b.json.gz"), "--yes"]) == 1
