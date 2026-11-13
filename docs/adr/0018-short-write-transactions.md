# 0018: Short write transactions in refreshes

Status: accepted (2026-11-12).

## Context

SQLite allows one writer at a time, and the API and the worker share one file
(ADR 0011). The refreshes (item pool, item data, dungeons, enchant recipes) wrote every
result in one transaction and committed at the end. From the second result on, each one
flushed and held the write lock while the next request went out. For the item pool that's
minutes. Any other writer, such as a second refresh, a sync or an edit, waited for the
10-second busy timeout and then failed with "database is locked" (HTTP 500).

## Decision

- **Loops that fetch over the network save each result with `db.save_now`:** a merge and a
  commit, so the write lock is held for milliseconds and never across a request.
- **The busy timeout stays at 10 seconds.** With short transactions, waits are short;
  raising the timeout would only hide a long transaction.
- A regression test writes from another connection, with no busy timeout, while a refresh
  is mid-way.

## Consequences

- Two refreshes, or a refresh and a sync, can run side by side.
- An interrupted refresh keeps what it fetched instead of rolling everything back.
- A long batch makes many small commits. That's cheap with WAL and `synchronous=NORMAL`.
- Concurrent writers at scale are #44's job (Postgres).
