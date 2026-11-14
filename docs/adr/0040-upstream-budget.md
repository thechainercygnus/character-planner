# 0040: One budget per upstream, shared by every job

Status: accepted (2026-11-14)

## Context

#17 asks that N concurrent syncs never exceed upstream rate limits. Each loop used to pace
itself with `time.sleep` (`COMPANION_REQUEST_PAUSE`), which holds only while one process
calls an upstream at a time. With queued jobs (ADR 0039), the web app, the worker and
several job workers can all call Battle.net or Forever Companion at once.

## Decision

1. **Every upstream request waits for room in its upstream's budget.**
   - The app's upstream HTTP clients all come from `upstream.client()`, whose request
     hook does the waiting: the Battle.net client, OAuth, Forever Companion items,
     dungeons and quests, and the queued sync.
   - A request over budget **waits** for the next window. It's never refused.
2. **The budgets sit below each published limit,** leaving room for anything else on the
   same IP or client:
   - **Forever Companion: 100 a minute,** against its 120 per IP.
   - **Blizzard (`*.api.blizzard.com`, `oauth.battle.net`): 50 a second and 30,000 an
     hour,** against 100 a second and 36,000 an hour per client.
   - Discord, for alerts, has none.
3. **Counted in fixed windows; each request is checked against all of its budget's
   windows at the same moment.** If any window is full, the request sleeps until the
   latest full window ends, and is checked against all of them again. A request is
   counted in every window or sent in none.
4. **Shared through Redis when there is one.**
   - With `REDIS_URL`, the counts are Redis keys (INCR with a TTL), so the web app and
     every job worker draw from one budget.
   - Without it, each process keeps its own counts. That suits a single-person instance,
     where one process at a time is busy.
   - Each process configures its budget at start (`upstream.configure`). Nothing reads
     settings implicitly, so tests never reach a developer's `.env`.
5. **The per-loop pauses stay.** They spread a batch out. The budget is the limit across
   batches and processes.

## Consequences

- **#17's load criterion** is covered by `test_concurrent_jobs_in_two_processes_share_one_budget`:
  threads in two "processes" share one store, and no window carries more than its limit.
- **Raising throughput** means changing `BUDGETS`, within the published limits.
- **Without Redis, a busy API and worker could each use the whole budget.** That needs
  two people on one SQLite instance at once, which is what Redis is for (ADR 0039).
