"""Export everything stored for one user, for an access request (#238, ADR 0056).

The admin area downloads it for the person who asked (`users.export`); the account page
(#217) offers the same file to each user for themselves, and to the one person when there
are no users (`export_everything`). It's JSON in a zip (Bryce,
2026-11-18):

- `account.json`: the account as stored (Battle.net account id, role, sign-up and last
  sign-in);
- `characters/<region>-<slug>/`: each character's row, then one file per table of its data
  (the tables a deletion empties, `characters.OWNED`): snapshots, progress, settings,
  game-data imports and the rest;
- `alerts.json`: their alert destinations, each webhook's URL masked.

Left out, and said so in `README.txt`: sign-in sessions and the Battle.net token (secrets,
stored only to sign in), and shared game data, which is nobody's.
"""

import io
import json
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

from sqlmodel import Session, SQLModel, col, select

from character_planner.characters import OWNED
from character_planner.db import Character, NotificationDestination, User
from character_planner.notify import masked

README = """Everything Character Planner stores for this account, as of {at}.

account.json        The account, with users on: its Battle.net account id, role, and when
                    it signed up and last signed in.
characters/         One folder per character: character.json, then one file per kind of
                    data stored for it (snapshots from Battle.net, progress history,
                    settings edited in the app, game-data imports and so on).
alerts.json         Alert destinations: Discord webhooks (each URL masked: it's a
                    credential) and Discord DMs.

Not included: sign-in sessions and the Battle.net sign-in token, which are secrets kept
only to sign in, and game data shared by every character (items, dungeons, recipes).
"""


def _rows(rows: Iterable[SQLModel]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]


def _write(archive: zipfile.ZipFile, name: str, data: Any) -> None:
    archive.writestr(name, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def export_user(session: Session, user_id: int, now: datetime | None = None) -> bytes:
    """One account's zip: the admin's export (#238), and the account page's (#217). Raises
    LookupError when there's no such user."""
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"No user {user_id}")
    characters = session.exec(
        select(Character).where(col(Character.user_id) == user_id).order_by(col(Character.id))
    ).all()
    destinations = session.exec(
        select(NotificationDestination)
        .where(col(NotificationDestination.user_id) == user_id)
        .order_by(col(NotificationDestination.id))
    ).all()
    return _archive(session, user, list(characters), list(destinations), now)


def export_everything(session: Session, now: datetime | None = None) -> bytes:
    """Without users (#217): one person's instance, so everything of theirs is everything:
    every character and every alert destination. No account.json: there's no account."""
    characters = session.exec(select(Character).order_by(col(Character.id))).all()
    destinations = session.exec(
        select(NotificationDestination).order_by(col(NotificationDestination.id))
    ).all()
    return _archive(session, None, list(characters), list(destinations), now)


def _archive(
    session: Session,
    user: User | None,
    characters: list[Character],
    destinations: list[NotificationDestination],
    now: datetime | None,
) -> bytes:
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(at=at))
        if user is not None:
            _write(
                archive,
                "account.json",
                user.model_dump(
                    mode="json", include={"account_id", "role", "created_at", "last_sign_in_at"}
                ),
            )
        for character in characters:
            folder = f"characters/{character.region}-{character.slug}"
            _write(archive, f"{folder}/character.json", character.model_dump(mode="json"))
            for table in OWNED:
                rows = session.exec(
                    select(table).where(col(table.character_id) == character.id)
                ).all()
                if rows:
                    name = str(cast(Any, table).__tablename__)
                    _write(archive, f"{folder}/{name}.json", _rows(cast(Any, rows)))
        alerts = _rows(destinations)
        for row in alerts:
            row["url"] = masked(row["url"]) if row["url"] else ""
        _write(archive, "alerts.json", alerts)
    return buffer.getvalue()


def filename(account_id: int | None, now: datetime | None = None) -> str:
    day = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    who = account_id if account_id is not None else "everything"
    return f"character-planner-{who}-{day}.zip"
