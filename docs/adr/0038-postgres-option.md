# 0038: Postgres as an option, SQLite as the default

Status: accepted (2026-11-14)

## Context

The app runs on one SQLite file that the API and the worker share (ADR 0011). SQLite
allows a single writer at a time. Short write transactions (ADR 0018) make that fine for
one person, but a shared service (#17), with several users syncing and editing at once,
needs a database built for concurrent writers (#44).

## Decision

1. **`DATABASE_URL` chooses the database.**
   - `sqlite:///...` stays the default, for development, tests and a single-person
     instance.
   - `postgresql+psycopg://...` runs it on Postgres. The app needs no other setting.
   - The driver is psycopg 3 (`psycopg[binary]`), a dependency of the app.
2. **The same migrations run on both** (ADR 0022). The schema was already portable:
   - JSON columns are SQLAlchemy's `JSON`;
   - timestamps are timezone-aware (`UTCDateTime`);
   - ids are integers well within 32 bits: Blizzard's largest seen is 25 bits;
   - the SQLite pragmas apply only to SQLite.

   Postgres connections are checked before use (`pool_pre_ping`).
3. **Postgres enforces foreign keys, and SQLite here doesn't.** Two deletion paths
   deleted parents before children. Postgres found them, and they're fixed:
   - `erase` now goes children first;
   - account deletion now removes the token before the user.
4. **The tests run on both.**
   - `TEST_DATABASE_URL` puts each test in a Postgres schema of its own, dropped
     afterwards.
   - CI's `postgres` job runs the whole suite that way, against a pinned Postgres 17
     service.
   - The SQLite write-lock test (ADR 0018) is skipped on Postgres, which has no such
     lock.
   - A test checks the migrations match the models on whichever database the suite
     uses.
5. **Moving an instance: `character-planner-db copy-to`.**
   - It copies `DATABASE_URL` into the database `COPY_TO_DATABASE_URL` names.
   - The target comes from the environment, so its password stays out of shell history
     and process lists, and output hides it.
   - It migrates both databases to the newest schema, refuses a target that already
     holds data, copies parents before children, and moves Postgres's id sequences past
     the copied ids.
6. **Compose:** `compose.postgres.yaml`, an override like `compose.tailscale.yaml`.
   - It adds a `postgres` service (pinned by digest, not published on the host, with its
     own volume) and points migrate, app and worker at it.
   - It needs `POSTGRES_PASSWORD` in `.env`. Plain `compose.yaml` stays on SQLite.

## When to pick which

- **SQLite:** one person, or a few people taking turns. It's one file to back up, and
  there's nothing else to run.
- **Postgres:** users on (ADR 0037) with several people using it at once, or the shared
  service (#17).

## Consequences

- **Backups differ.** Postgres needs `pg_dump`, where SQLite was a file copy. The
  self-hosting guide covers both.
- **CI runs a Postgres service.** Making the `postgres` job required is the repository
  owner's call, in the ruleset.
