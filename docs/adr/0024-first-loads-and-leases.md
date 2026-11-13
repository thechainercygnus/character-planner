# 0024: First data loads, refresh leases and worker retries

Status: accepted (2026-11-13).

## Context

The first beta-test instance sat empty after its first sync (#87):
- the worker had skipped its pool job before anyone logged in, and counted the skip as a
  run, so the next attempt was 24 hours away;
- the enchant refresh had no schedule;
- one pool refresh got an empty dungeon list from Forever Companion and reported no error.

Loading data automatically means the API and the worker may both start a refresh. Two at
once would fetch everything twice and break Forever Companion's limit of 120 requests a
minute.

## Decision

- **Leases** (`JobLease`, migration 0002): each long refresh ("pool", "enchants") takes a
  lease before running, by an atomic insert, or an update of an expired row.
  - Whoever doesn't get it is busy: the API answers 409, the worker and the background
    load skip.
  - A lease expires after 2 hours, in case its process dies.
  - `/api/status` lists the leases held as `refreshing`, and the status bar shows
    "Loading … in the background" until they finish, then reloads the page's data.
- **The first sync loads what's missing.** If there's no dungeon data or no enchant
  recipes, the sync starts those refreshes as a background task after its response.
- **The worker retries a skipped job** (no login, no level yet, already running) after 2
  minutes instead of a whole interval. A repeated identical outcome is logged at DEBUG.
  The enchant refresh is scheduled weekly (`ENCHANTS_EVERY_HOURS`, default 168).
- **An empty upstream list is an error.**
  - The dungeon list logs what came back (status, top-level keys, size), tries once more
    after a pause, and reports "empty response" if it's still empty.
  - The worker counts that as urgent for the upstream system alert (#12), as it does a
    rate limit.

## Consequences

- A fresh instance has its data a few minutes after the first sync, with no menu clicks.
- The ⋯ menu's refresh buttons stay for forcing a refresh. #17 moves them to the operator.
- Leases live in the database, so they work across the API and the worker, and on
  Postgres later (#44).
