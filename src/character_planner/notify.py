"""Notifications, stage 1 (#12, ADR 0021): alerts to Discord webhooks.

Two audiences (ADR 0020). User alerts are about a character: level-ups, targets reached
or now in reach, new upgrades. System alerts are for whoever
runs the instance: a scheduled job failed, or upstream services errored. System alerts go
to system destinations, or to user destinations when there are none (a self-hosted copy).

Flow: jobs report what happened (after_sync, job_failed, upstream_errors),
which queues a Discord message per subscribed destination in the outbox. The worker sends
what's due (deliver_due): Discord's 429 retry_after is respected, other failures are
retried with backoff, and a webhook that's gone marks its destination failing.

Change detection compares a digest of the character with the one from the previous sync,
so a sync where nothing changed sends nothing, and the first sync only sets the baseline.
"""

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from character_planner import fields
from character_planner.config import Settings
from character_planner.crafting import crafted_items
from character_planner.db import (
    Character,
    NotificationDestination,
    NotificationOutbox,
    NotificationState,
    owned,
    save_owned,
    utcnow,
)

# A Discord webhook message: JSON, as Discord's API takes it.
Message = dict[str, Any]

logger = logging.getLogger(__name__)

AlertKind = Literal[
    "level_up",
    "target_reached",
    "target_in_reach",
    "new_upgrade",
    "job_failed",
    "upstream_errors",
]
Audience = Literal["user", "system"]


class AlertInfo(BaseModel):
    kind: AlertKind
    audience: Audience
    label: str


ALERTS: list[AlertInfo] = [
    AlertInfo(kind="level_up", audience="user", label="Level-ups"),
    AlertInfo(kind="target_reached", audience="user", label="Gear target reached"),
    AlertInfo(kind="target_in_reach", audience="user", label="Coming-up target now in reach"),
    AlertInfo(kind="new_upgrade", audience="user", label="New upgrades worth having"),
    AlertInfo(kind="job_failed", audience="system", label="A scheduled job failed"),
    AlertInfo(kind="upstream_errors", audience="system", label="Upstream errors"),
]
AUDIENCE: dict[str, Audience] = {a.kind: a.audience for a in ALERTS}
USER_ALERTS = [a.kind for a in ALERTS if a.audience == "user"]
# Alerts no longer sent. Destinations may still list them: they're dropped when read or
# saved, so an old destination doesn't fail validation. The login alerts went with #107:
# syncs no longer need the 24-hour login.
RETIRED_ALERTS = {"login_expiring", "login_expired"}
SYSTEM_ALERTS = [a.kind for a in ALERTS if a.audience == "system"]

# Only Discord's own webhook addresses are accepted, so a destination can't make the app
# send requests anywhere else.
WEBHOOK_URL = re.compile(
    r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/"
    r"(?P<id>\d{5,25})/(?P<token>[A-Za-z0-9_-]{20,100})"
)

UPGRADE_MIN_GAIN = 3.0  # score gain an upgrade needs to be worth an alert
UPGRADES_LISTED = 3
UPSTREAM_ERROR_THRESHOLD = 10  # errors in one refresh before it's worth an alert
MAX_ATTEMPTS = 5
BACKOFF = [timedelta(minutes=m) for m in (1, 5, 15, 60)]
COLOR = {"user": 0x3BA55C, "system": 0xED4245}


class NotifyError(ValueError):
    """A destination that can't be saved (status 422)."""


def valid_webhook(url: str) -> str:
    url = url.strip()
    if not WEBHOOK_URL.fullmatch(url):
        raise NotifyError("Paste a Discord webhook URL (https://discord.com/api/webhooks/…)")
    return url


def masked(url: str) -> str:
    """The webhook URL with its token hidden: enough to recognise, not to use."""
    match = WEBHOOK_URL.fullmatch(url)
    return f"…/webhooks/{match['id']}/••••" if match else "••••"


def clean_alerts(alerts: Iterable[str], audience: Audience) -> list[str]:
    """Known alerts, in the standard order. System destinations take system alerts only."""
    wanted = set(alerts) - RETIRED_ALERTS
    unknown = wanted - set(AUDIENCE)
    if unknown:
        raise NotifyError(f"Unknown alerts: {', '.join(sorted(unknown))}")
    if audience == "system" and wanted - set(SYSTEM_ALERTS):
        raise NotifyError("A system destination only takes system alerts")
    return [a.kind for a in ALERTS if a.kind in wanted]


def default_alerts(audience: Audience) -> list[str]:
    # A user destination gets the system alerts too: on a self-hosted copy the user is the
    # operator (ADR 0020). They only arrive there while no system destination exists.
    return USER_ALERTS + SYSTEM_ALERTS if audience == "user" else list(SYSTEM_ALERTS)


# --- queueing ------------------------------------------------------------------------------


def _recipients(session: Session, kind: str) -> list[NotificationDestination]:
    enabled = session.exec(
        select(NotificationDestination).where(col(NotificationDestination.enabled))
    ).all()
    subscribed = [d for d in enabled if kind in (d.alerts or [])]
    if AUDIENCE.get(kind) == "user":
        return [d for d in subscribed if d.audience == "user"]
    system = [d for d in subscribed if d.audience == "system"]
    if any(d.audience == "system" for d in enabled):
        return system
    return [d for d in subscribed if d.audience == "user"]


def _queue(
    session: Session, destination: NotificationDestination, kind: str, key: str, message: Message
) -> bool:
    """Queue one message unless this destination already has this key; True if queued."""
    assert destination.id is not None
    exists = session.exec(
        select(NotificationOutbox).where(
            NotificationOutbox.destination_id == destination.id,
            NotificationOutbox.dedupe_key == key,
        )
    ).first()
    if exists is not None:
        return False
    session.add(
        NotificationOutbox(
            destination_id=destination.id, kind=kind, dedupe_key=key, payload=message
        )
    )
    try:
        session.commit()
    except IntegrityError:  # queued by another process meanwhile
        session.rollback()
        return False
    return True


def _message(title: str, description: str, color: int, url: str | None = None) -> Message:
    embed: dict[str, Any] = {
        "title": title[:256],
        "description": description[:4000],
        "color": color,
    }
    if url:
        embed["url"] = url
    # No pings, whatever an item or character name contains.
    return {"username": "Character Planner", "embeds": [embed], "allowed_mentions": {"parse": []}}


def app_url(settings: Settings, tab: str = "") -> str | None:
    """The app's address, from the Battle.net redirect URI (they share a host)."""
    parts = urlsplit(settings.bnet_redirect_uri)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/" + (f"#{tab}" if tab else "")


def notify(session: Session, kind: AlertKind, key: str, message: Message) -> int:
    """Queue an alert for every destination that wants it; how many were queued."""
    return sum(_queue(session, d, kind, key, message) for d in _recipients(session, kind))


# --- system alerts ---------------------------------------------------------------------


def job_failed(session: Session, settings: Settings, job: str, error: str) -> None:
    hour = utcnow().strftime("%Y-%m-%dT%H")
    notify(
        session,
        "job_failed",
        f"job_failed:{job}:{hour}",
        _message(f"Scheduled {job} failed", error[:500], COLOR["system"], app_url(settings)),
    )


def upstream_errors(
    session: Session, settings: Settings, job: str, errors: list[str], rate_limited: bool
) -> None:
    if len(errors) < UPSTREAM_ERROR_THRESHOLD and not rate_limited:
        return
    hour = utcnow().strftime("%Y-%m-%dT%H")
    head = "Stopped at a rate limit. " if rate_limited else ""
    sample = "\n".join(f"• {e}" for e in errors[:5])
    notify(
        session,
        "upstream_errors",
        f"upstream_errors:{job}:{hour}",
        _message(
            f"{job}: {len(errors)} upstream errors",
            f"{head}First few:\n{sample}",
            COLOR["system"],
            app_url(settings),
        ),
    )


# --- character changes ---------------------------------------------------------------


class Digest(BaseModel):
    """The character as alerts see it, kept from one sync to the next."""

    level: int | None = None
    targets: dict[str, str] = {}  # slot -> current target ("item id" or name)
    reached: list[str] = []  # "slot:target" worn
    upgrades: list[int] = []  # item ids of alert-worthy upgrades
    names: dict[str, str] = {}  # target key -> name, for messages


def _target_key(item_id: int | None, name: str) -> str:
    return str(item_id) if item_id is not None else name.casefold()


def character_digest(
    session: Session, settings: Settings, character_id: int | None
) -> tuple[Digest, list[str]]:
    """The digest now, and the alert-worthy upgrades as text lines, best first."""
    from character_planner import jobs  # jobs calls after_sync: import here, not on load
    from character_planner.choices import stored_choices
    from character_planner.classes import current_defaults
    from character_planner.companion import companion_by_id
    from character_planner.db import catalog_by_name, icons_by_id, latest_by_kind
    from character_planner.pool import pool_view
    from character_planner.recommend import recommend
    from character_planner.rules import current_rules
    from character_planner.scoring import current_weights
    from character_planner.views import character_level, gear_plan, parse_equipment

    latest = latest_by_kind(session, character_id)
    defaults = current_defaults(session, settings.curated_dir, character_id)
    weights = current_weights(session, defaults.presets, character_id)
    targets = jobs.gear_targets(session, settings, character_id)
    plan = gear_plan(
        latest,
        targets,
        catalog_by_name(session),
        icons_by_id(session),
        companion_by_id(session),
        weights,
        jobs.item_levels(session, character_id),
    )
    level, faction = jobs.character_context(session, character_id)
    equipment = latest.get("equipment")
    equipped = {i.slot: i for i in parse_equipment(equipment.payload if equipment else None)}
    rules = current_rules(session, defaults.rules, character_id)
    recs = recommend(
        pool_view(session, level, faction, crafted_items(session, character_id)),
        equipped,
        weights,
        rules,
        targets,
        stored_choices(session, character_id),
    )

    digest = Digest(
        level=character_level(latest["profile"].payload) if "profile" in latest else None
    )
    for row in plan.rows:
        key = _target_key(row.target.item_id, row.target.item)
        digest.targets[row.slot] = key
        digest.names[key] = row.target.item
        if row.reached:
            digest.reached.append(f"{row.slot}:{key}")

    best: dict[int, tuple[float, str, str, str]] = {}
    # Without a level the pool isn't windowed, so every item in the game would compete:
    # no upgrade alerts until a sync has a level (a failed profile request, for example).
    for row in recs.rows if level is not None else []:
        for c in row.candidates:
            if c.usable_now and c.score_gain >= UPGRADE_MIN_GAIN:
                source = c.item.sources[0].place if c.item.sources else "?"
                current = best.get(c.item.item_id)
                if current is None or c.score_gain > current[0]:
                    best[c.item.item_id] = (c.score_gain, c.item.name, row.slot, source)
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:UPGRADES_LISTED]
    digest.upgrades = [item_id for item_id, _ in ranked]
    lines = [
        f"**{name}** ({slot.replace('_', ' ').title()}, {source}): +{gain:.1f}"
        for _, (gain, name, slot, source) in ranked
    ]
    return digest, lines


def _load_digest(session: Session, character_id: int | None) -> Digest | None:
    row = owned(session, NotificationState, character_id, key="digest")
    return Digest.model_validate(row.value) if row else None


def _save_digest(session: Session, digest: Digest, character_id: int | None) -> None:
    values = {"value": digest.model_dump(), "updated_at": utcnow()}
    save_owned(session, NotificationState, character_id, {"key": "digest"}, values)
    session.commit()


def after_sync(session: Session, settings: Settings, character: Character) -> int:
    """Queue alerts for what changed since the last sync; how many messages were queued.

    One message per destination, with a section for each change it subscribes to. The
    first sync only records the baseline."""
    if not session.exec(select(NotificationDestination)).first():
        return 0  # nothing to send to: don't even build the digest
    now, upgrade_lines = character_digest(session, settings, character.id)
    before = _load_digest(session, character.id)
    _save_digest(session, now, character.id)
    if before is None:
        logger.info("Notifications: first sync recorded as the baseline")
        return 0

    sections: dict[str, str] = {}
    if now.level is not None and before.level is not None and now.level > before.level:
        sections["level_up"] = f"Reached **level {now.level}**."
    reached = [r for r in now.reached if r not in before.reached]
    if reached:
        pairs = [r.split(":", 1) for r in reached]
        sections["target_reached"] = "\n".join(
            f"• {now.names.get(key, key)} ({slot.replace('_', ' ').title()})" for slot, key in pairs
        )
    in_reach = [
        (slot, key)
        for slot, key in now.targets.items()
        if before.targets.get(slot) != key and f"{slot}:{key}" not in now.reached
    ]
    if in_reach:
        sections["target_in_reach"] = "\n".join(
            f"• {now.names.get(key, key)} ({slot.replace('_', ' ').title()})"
            for slot, key in in_reach
        )
    if set(now.upgrades) - set(before.upgrades):
        sections["new_upgrade"] = "\n".join(upgrade_lines)
    if not sections:
        return 0

    titles = {
        "level_up": "Level-up",
        "target_reached": "Targets reached",
        "target_in_reach": "Targets now in reach",
        "new_upgrade": "Upgrades worth having",
    }
    key = f"sync:{utcnow().strftime('%Y-%m-%dT%H:%M')}:" + ",".join(sorted(sections))
    queued = 0
    for destination in session.exec(
        select(NotificationDestination).where(
            col(NotificationDestination.enabled), NotificationDestination.audience == "user"
        )
    ).all():
        wanted = [k for k in sections if k in (destination.alerts or [])]
        if not wanted:
            continue
        name = f"{character.name} {character.surname}".strip()
        message = _message(f"{name}: what changed", "", COLOR["user"], app_url(settings, "plan"))
        message["embeds"][0]["fields"] = [
            {"name": titles[k], "value": sections[k][:1000], "inline": False} for k in wanted
        ]
        del message["embeds"][0]["description"]
        queued += _queue(session, destination, wanted[0], key, message)
    logger.info("Notifications: %s changed, %d messages queued", ", ".join(sections), queued)
    return queued


# --- delivery ----------------------------------------------------------------------------


class SendResult(BaseModel):
    ok: bool
    status: int | None = None
    error: str | None = None
    retry_after: float | None = None
    gone: bool = False  # the webhook no longer exists or isn't allowed


def send(http: httpx.Client, url: str, message: Message) -> SendResult:
    try:
        response = http.post(url, json=message, timeout=10)
    except httpx.HTTPError as error:
        return SendResult(ok=False, error=f"{error.__class__.__name__}")
    if response.status_code in (200, 204):
        return SendResult(ok=True, status=response.status_code)
    if response.status_code == 429:
        try:
            retry = float(response.json().get("retry_after", 5))
        except ValueError:
            retry = 5.0
        return SendResult(ok=False, status=429, error="rate limited", retry_after=retry)
    gone = response.status_code in (401, 403, 404)
    return SendResult(
        ok=False, status=response.status_code, error=f"HTTP {response.status_code}", gone=gone
    )


def deliver_due(session: Session, http: httpx.Client, now: datetime | None = None) -> int:
    """Send every queued message that's due; how many were sent."""
    now = now or utcnow()
    due = session.exec(
        select(NotificationOutbox)
        .where(
            col(NotificationOutbox.sent_at).is_(None),
            col(NotificationOutbox.failed).is_(False),
            col(NotificationOutbox.next_attempt_at) <= now,
        )
        .order_by(col(NotificationOutbox.id))
    ).all()
    sent = 0
    for item in due:
        destination = session.get(NotificationDestination, item.destination_id)
        if destination is None or not destination.enabled:
            item.failed, item.last_error = True, "destination removed or disabled"
            session.add(item)
            session.commit()
            continue
        result = send(http, destination.url, item.payload)
        item.attempts += 1
        if result.ok:
            item.sent_at = utcnow()
            destination.last_sent_at, destination.last_error = item.sent_at, None
            sent += 1
        elif result.gone:
            item.failed, item.last_error = True, result.error
            destination.last_error = f"{result.error}: the webhook may have been deleted"
            logger.warning("Notification to %r failed for good: %s", destination.name, result.error)
        elif result.retry_after is not None:
            item.next_attempt_at = utcnow() + timedelta(seconds=result.retry_after)
            item.last_error = result.error
            session.add(item)
            session.add(destination)
            session.commit()
            break  # Discord asked us to wait: the rest waits too
        elif item.attempts >= MAX_ATTEMPTS:
            item.failed, item.last_error = True, result.error
            destination.last_error = result.error
            logger.warning(
                "Notification to %r failed after %d attempts: %s",
                destination.name,
                item.attempts,
                result.error,
            )
        else:
            item.next_attempt_at = utcnow() + BACKOFF[min(item.attempts - 1, len(BACKOFF) - 1)]
            item.last_error = result.error
        session.add(item)
        session.add(destination)
        session.commit()
    if sent:
        logger.info("Notifications: %d sent", sent)
    return sent


def new_client() -> httpx.Client:
    return httpx.Client(timeout=10, headers={"User-Agent": "character-planner"})


# --- settings ------------------------------------------------------------------------------


class DestinationView(BaseModel):
    """A destination as the app shows it: the URL masked."""

    id: int
    name: str
    kind: str
    audience: Audience
    url: str
    alerts: list[str]
    enabled: bool
    last_sent_at: datetime | None
    last_error: str | None


class RecentView(BaseModel):
    destination: str
    kind: str
    created_at: datetime
    sent_at: datetime | None
    failed: bool
    attempts: int
    last_error: str | None


class NotificationsView(BaseModel):
    destinations: list[DestinationView]
    alerts: list[AlertInfo] = ALERTS
    recent: list[RecentView]  # the latest 20 messages, newest first
    # True when system alerts go to user destinations (no system destination exists).
    system_alerts_to_user: bool


class NewDestination(BaseModel):
    name: str
    url: str
    audience: Audience = "user"
    alerts: list[str] | None = None  # None: the defaults for the audience


class DestinationUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    alerts: list[str] | None = None
    enabled: bool | None = None


def _clean_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise NotifyError("Names are 1 to 60 characters")
    return name


def _audience(destination: NotificationDestination) -> Audience:
    return "system" if destination.audience == "system" else "user"


def _view(d: NotificationDestination) -> DestinationView:
    assert d.id is not None
    return DestinationView(
        id=d.id,
        name=d.name,
        kind=d.kind,
        audience=_audience(d),
        url=masked(d.url),
        alerts=[a for a in fields.as_list(d.alerts) if a not in RETIRED_ALERTS],
        enabled=d.enabled,
        last_sent_at=d.last_sent_at,
        last_error=d.last_error,
    )


def notifications_view(session: Session) -> NotificationsView:
    destinations = session.exec(
        select(NotificationDestination).order_by(col(NotificationDestination.id))
    ).all()
    names = {d.id: d.name for d in destinations}
    recent = session.exec(
        select(NotificationOutbox).order_by(col(NotificationOutbox.id).desc()).limit(20)
    ).all()
    return NotificationsView(
        destinations=[_view(d) for d in destinations],
        recent=[
            RecentView(
                destination=names.get(r.destination_id, "(removed)"),
                kind=r.kind,
                created_at=r.created_at,
                sent_at=r.sent_at,
                failed=r.failed,
                attempts=r.attempts,
                last_error=r.last_error,
            )
            for r in recent
        ],
        system_alerts_to_user=not any(d.audience == "system" and d.enabled for d in destinations),
    )


def add_destination(session: Session, new: NewDestination) -> NotificationDestination:
    alerts = default_alerts(new.audience) if new.alerts is None else new.alerts
    destination = NotificationDestination(
        name=_clean_name(new.name),
        audience=new.audience,
        url=valid_webhook(new.url),
        alerts=clean_alerts(alerts, new.audience),
    )
    session.add(destination)
    session.commit()
    session.refresh(destination)
    logger.info("Notifications: added %s destination %r", destination.audience, destination.name)
    return destination


def update_destination(
    session: Session, destination: NotificationDestination, update: DestinationUpdate
) -> None:
    if update.name is not None:
        destination.name = _clean_name(update.name)
    if update.url is not None:
        destination.url = valid_webhook(update.url)
        destination.last_error = None
    if update.alerts is not None:
        destination.alerts = clean_alerts(update.alerts, _audience(destination))
    if update.enabled is not None:
        destination.enabled = update.enabled
    session.add(destination)
    session.commit()


def remove_destination(session: Session, destination: NotificationDestination) -> None:
    for item in session.exec(
        select(NotificationOutbox).where(NotificationOutbox.destination_id == destination.id)
    ).all():
        session.delete(item)
    session.delete(destination)
    session.commit()
    logger.info("Notifications: removed destination %r", destination.name)


def send_test(
    session: Session, settings: Settings, destination: NotificationDestination, http: httpx.Client
) -> SendResult:
    """Send a test message straight away, outside the outbox."""
    result = send(
        http,
        destination.url,
        _message(
            "Test alert from Character Planner",
            f"Alerts for **{destination.name}** will arrive here.",
            COLOR[_audience(destination)],
            app_url(settings),
        ),
    )
    if result.ok:
        destination.last_sent_at, destination.last_error = utcnow(), None
    else:
        destination.last_error = result.error
    session.add(destination)
    session.commit()
    return result
