# 0041: Readiness and Prometheus metrics

Status: accepted (2026-11-14)

## Context

Running the planner as a shared service (#17) needs a way to see whether it can serve,
and how it's doing. Health (`/api/healthz`, for the container check), structured logs
(ADR 0019) and backups (the self-hosting guide) already existed. Readiness and metrics
didn't.

## Decision

1. **`GET /api/readyz`: can this instance serve?**
   - Checks that the database answers and its schema is at the newest migration, and,
     with `REDIS_URL`, that the job queue answers.
   - 200 when everything passes. Otherwise 503, naming each failed check with the error's
     type only, never its message or internals.
   - `/api/healthz` stays the cheap "is the process up" check that the container uses.
2. **`GET /api/metrics`: Prometheus text format, off by default.**
   - Off (404) unless `METRICS_TOKEN` is set. Then a scrape sends
     `Authorization: Bearer <token>`, compared in constant time; anything else gets 401.
   - The token is never logged. Usage numbers aren't public by default, even without
     users on.
3. **What's measured:**
   - `planner_http_requests_total` and `planner_http_request_duration_seconds`, by method
     and **route template** (`/api/choices/{item_id}`), so ids never become labels. The
     web app's own files are one `static` label.
   - `planner_characters`, `planner_users`, and `planner_oldest_sync_age_seconds` (the
     least recently synced character, for an alert when syncs stop).
   - `planner_queue_jobs` by state, with `REDIS_URL`: queued, started, failed.
   - `planner_upstream_budget_waits_total` by upstream (ADR 0040), in the API process.
   - `planner_info` with the version.
4. **`prometheus-client`**, with a registry per app, so tests can build as many as they
   like. Counts and gauges are read from the database and the queue at scrape time.
5. **Readiness and metrics need no sign-in with users on** (ADR 0037). Readiness says
   nothing about anyone's data, and metrics has its own token. Both log at DEBUG, like
   `/api/healthz`, because they're polled every few seconds.

## Consequences

- **Per-process numbers:** request counts and budget waits are the API process's own. The
  worker and job worker aren't scraped. Queue depth, characters, users and sync age come
  from shared state, so they cover everything.
- **#17's "Operating it"** is met: health, readiness, structured logs, basic metrics and
  backups.
