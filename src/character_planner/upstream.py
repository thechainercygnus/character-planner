"""The upstream budget (#17, ADR 0040): every request to Battle.net or Forever Companion
waits for room in its budget, so syncs and refreshes running side by side stay within
their limits together.

The budgets are counted in fixed windows. With REDIS_URL the counts live in Redis, shared
by the web app and every job worker. Without it they're per process, which suits a
single-person instance. A request over budget waits for the next window: it's never
refused.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# redis-py is only partly typed; the code here stays strict otherwise.

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from character_planner.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Window:
    seconds: int
    limit: int


# Below each upstream's published limit, with room for others on the same IP or client.
BUDGETS: dict[str, tuple[Window, ...]] = {
    # 120 requests a minute per IP (forevercompanion.io/api).
    "forevercompanion": (Window(60, 100),),
    # Blizzard's API: 100 requests a second and 36,000 an hour per client.
    "blizzard": (Window(1, 50), Window(3600, 30_000)),
}


def budget_name(host: str) -> str | None:
    """Which budget a host draws from; None for hosts with none (Discord, for alerts)."""
    if host == "forevercompanion.io" or host.endswith(".forevercompanion.io"):
        return "forevercompanion"
    if host.endswith(".api.blizzard.com") or host == "oauth.battle.net":
        return "blizzard"
    return None


# How often requests waited for room, per upstream, in this process (for metrics).
WAITS: dict[str, int] = {}


class Store(Protocol):
    def add(self, key: str, ttl: int) -> int:
        """Count one more request under key, and return the count so far."""
        ...


class LocalStore:
    """Counts for this process only."""

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def add(self, key: str, ttl: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, expires = self._counts.get(key, (0, now + ttl))
            if expires <= now:
                count, expires = 0, now + ttl
            self._counts[key] = (count + 1, expires)
            for stale in [k for k, (_, e) in self._counts.items() if e <= now]:
                del self._counts[stale]
            return count + 1


class RedisStore:
    """Counts shared by every process using the same Redis."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def add(self, key: str, ttl: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        count, _ = pipe.execute()
        return int(count)


class Budget:
    def __init__(
        self,
        store: Store,
        budgets: dict[str, tuple[Window, ...]] = BUDGETS,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store, self._budgets, self._clock, self._sleep = store, budgets, clock, sleep

    def wait(self, host: str) -> None:
        """Block until a request to host fits its budget, then count it."""
        name = budget_name(host)
        if name is None:
            return
        windows = self._budgets.get(name, ())
        while windows:
            # Every window at the same moment: a request counts in each, or waits for
            # the latest of the full ones to end and tries them all again.
            now = self._clock()
            waits: list[float] = []
            for window in windows:
                slot = int(now // window.seconds)
                key = f"budget:{name}:{window.seconds}:{slot}"
                if self._store.add(key, window.seconds + 1) > window.limit:
                    waits.append((slot + 1) * window.seconds - now)
            if not waits:
                return
            WAITS[name] = WAITS.get(name, 0) + 1
            logger.debug("Upstream budget: %s is full for %.1fs", name, max(waits))
            self._sleep(max(max(waits), 0.01))


_budget = Budget(LocalStore())


def configure(settings: Settings) -> None:
    """Called once by each process (API, worker, job worker) at start: share the budget
    through Redis when REDIS_URL is set (ADR 0040), else keep it in this process."""
    global _budget
    if settings.redis_url:
        from character_planner import queue

        _budget = Budget(RedisStore(queue.connect(settings.redis_url)))
    else:
        _budget = Budget(LocalStore())


def use(budget: Budget) -> None:
    """Swap the budget: tests use an unlimited one, or a small one to check limits."""
    global _budget
    _budget = budget


def _wait_for_budget(request: httpx.Request) -> None:
    _budget.wait(request.url.host)


def client(**kwargs: Any) -> httpx.Client:
    """An HTTP client for Battle.net or Forever Companion, held to the shared budget.
    Every upstream client the app makes comes from here."""
    hooks: dict[str, list[Callable[..., Any]]] = {"request": [_wait_for_budget]}
    kwargs.setdefault("timeout", 20)
    return httpx.Client(event_hooks=hooks, **kwargs)
