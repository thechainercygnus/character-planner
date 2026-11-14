"""The upstream budget (#17, ADR 0040): requests to Battle.net and Forever Companion,
from any number of jobs and processes at once, stay within each upstream's limits."""

import threading
import time
from collections import Counter
from typing import Any

import fakeredis
import httpx
import pytest
import respx

from character_planner import queue, upstream
from character_planner.config import Settings
from character_planner.upstream import Budget, LocalStore, RedisStore, Window, budget_name


@pytest.mark.parametrize(
    ("host", "budget"),
    [
        ("forevercompanion.io", "forevercompanion"),
        ("us.api.blizzard.com", "blizzard"),
        ("eu.api.blizzard.com", "blizzard"),
        ("oauth.battle.net", "blizzard"),
        ("discord.com", None),  # alerts aren't an upstream with a budget
        ("api.blizzard.com.example.org", None),
    ],
)
def test_each_host_draws_from_its_upstreams_budget(host: str, budget: str | None) -> None:
    assert budget_name(host) == budget


class FakeTime:
    """A clock that only moves when the budget sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


def test_a_full_window_waits_for_the_next_one() -> None:
    fake = FakeTime()
    small = {"forevercompanion": (Window(10, 3),)}
    budget = Budget(LocalStore(), small, clock=fake.clock, sleep=fake.sleep)
    sent: list[float] = []
    for _ in range(7):
        budget.wait("forevercompanion.io")
        sent.append(fake.now)
    per_window = Counter(int(t // 10) for t in sent)
    assert max(per_window.values()) == 3
    assert fake.slept == [10.0, 10.0]  # to the start of each next window, never more


def test_every_window_of_a_budget_holds() -> None:
    fake = FakeTime()
    both = {"blizzard": (Window(1, 2), Window(10, 5))}
    budget = Budget(LocalStore(), both, clock=fake.clock, sleep=fake.sleep)
    sent: list[float] = []
    for _ in range(12):
        budget.wait("us.api.blizzard.com")
        sent.append(fake.now)
    assert max(Counter(int(t) for t in sent).values()) <= 2
    assert max(Counter(int(t // 10) for t in sent).values()) <= 5


def test_hosts_without_a_budget_never_wait() -> None:
    fake = FakeTime()
    budget = Budget(LocalStore(), {}, clock=fake.clock, sleep=fake.sleep)
    for _ in range(50):
        budget.wait("discord.com")
    assert fake.slept == []


def test_concurrent_jobs_in_two_processes_share_one_budget() -> None:
    """#17: N concurrent syncs don't exceed an upstream's limit. Three threads in each of
    two "processes" (separate Budgets over one Redis) send 12 requests together; no
    one-second window ever carries more than the limit."""
    redis = fakeredis.FakeStrictRedis()
    limit = 4
    small = {"blizzard": (Window(1, limit),)}
    processes = [Budget(RedisStore(redis), small), Budget(RedisStore(redis), small)]
    sent: list[float] = []
    lock = threading.Lock()

    def job(budget: Budget) -> None:
        for _ in range(2):
            budget.wait("us.api.blizzard.com")
            with lock:
                sent.append(time.time())

    threads = [threading.Thread(target=job, args=(b,)) for b in processes for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(sent) == 12
    assert max(Counter(int(t) for t in sent).values()) <= limit


@respx.mock
def test_upstream_clients_wait_for_the_budget() -> None:
    hosts: list[str] = []

    class Recorder(Budget):
        def wait(self, host: str) -> None:
            hosts.append(host)

    upstream.use(Recorder(LocalStore()))
    respx.get("https://forevercompanion.io/api/v1/items/1").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://us.api.blizzard.com/data/x").mock(return_value=httpx.Response(200, json={}))
    with upstream.client() as http:
        http.get("https://forevercompanion.io/api/v1/items/1")
        http.get("https://us.api.blizzard.com/data/x")
    assert hosts == ["forevercompanion.io", "us.api.blizzard.com"]


def test_the_budget_is_shared_through_redis_when_there_is_one(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(queue, "connect", lambda _url: fake)
    upstream.configure(settings.model_copy(update={"redis_url": "redis://fake"}))
    store: Any = upstream._budget._store  # pyright: ignore[reportPrivateUsage]
    assert isinstance(store, RedisStore)
    upstream.configure(settings)
    store = upstream._budget._store  # pyright: ignore[reportPrivateUsage]
    assert isinstance(store, LocalStore)
