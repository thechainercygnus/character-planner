# 0039: Background jobs on Redis with RQ, and a sync cooldown

Status: accepted (2026-11-14)

## Context

A Sync ran inside the web request: about a dozen Battle.net calls, then item lookups,
for several seconds. With several users (#17), that ties up web workers, and a burst of
Syncs hits Battle.net all at once. #17 asks for user-triggered work to run as background
jobs the page polls, within the upstream budget.

The options were a job table in the existing database, worked by the existing worker, or
Redis with a job library. Bryce chose Redis with a job library (2026-11-14).

## Decision

1. **RQ on a Redis-protocol server, and optional.**
   - **Without `REDIS_URL`,** a Sync runs in the web request as before. A single-person
     instance needs nothing new.
   - **With `REDIS_URL`,** `POST /api/sync` queues a job and answers 202. `GET /api/sync`
     reports it: queued, started, finished (with each endpoint's status), or failed (with
     why). The page polls it every 2 seconds.
   - RQ suits this code, which is synchronous (SQLModel sessions, httpx).
2. **One sync per character at a time.**
   - Its job id is `sync-<character>`. Syncing again while one waits or runs returns that
     one.
   - The state is read through the request's character, so another user's sync answers
     404, like everything else (ADR 0037).
3. **The worker container works the queue.**
   - With `REDIS_URL`, `character-planner-worker` runs `character-planner-jobs` as a
     child process. The child shares the container's settings, so the Postgres override
     (ADR 0038) reaches it too.
   - The child is restarted if it exits, and stopped with the worker; RQ finishes the job
     it's on.
   - `character-planner-jobs` uses RQ's `SimpleWorker`. That works on Windows too, and
     jobs share one connection pool.
4. **The server is Valkey** (`compose.redis.yaml`), the BSD-licensed, Redis-compatible
   fork. Redis 7.4 and later aren't open source. It's pinned by digest, not published,
   and keeps nothing on disk: jobs and their results last an hour.
5. **A manual Sync waits 15 minutes per character** (`SYNC_COOLDOWN_MINUTES`; 0 turns it
   off). Bryce chose 15 (2026-11-14).
   - It counts from the character's last sync, scheduled ones included.
   - A Sync within it answers 429 with `Retry-After`, and the page shows when to try
     again.
   - It applies with and without the queue.

6. **The admin's bulk refreshes queue too** (#17 step 2b): the item pool, enchants,
   items and talents.
   - With `REDIS_URL`, each one answers 202 and runs on the job worker, one job per kind.
   - Queued and running refreshes join the status bar's "refreshing" list, which already
     reloads the page when it empties.
   - Without Redis, they run in the request, as before. Leases (ADR 0024) still keep each
     refresh to one at a time either way.
7. **Each refresh can be started by hand at most once per 10 minutes**
   (`REFRESH_COOLDOWN_MINUTES`; 0 turns it off).
   - Within that it answers 429 with `Retry-After`. That holds for the admin too, and
     completes #17's "operator-only and rate-limited".
   - The worker's schedule isn't limited.
   - The cooldown is a lease that's never released: every process sees it, and it
     simply expires.

## Consequences

- **A shared instance runs three more pieces:** Valkey, plus the job worker inside the
  worker container.
- **Every job is within the upstream budget** (ADR 0040).
- **Scaling:** more job workers mean more replicas of the worker container. Each also
  runs the schedule, and its leases (ADR 0024) keep the refreshes one at a time.
