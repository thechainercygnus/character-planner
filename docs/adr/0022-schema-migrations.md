# 0022: Schema migrations with Alembic

Status: accepted (2026-11-13).

## Context

Tables were created with `create_all`, which adds missing tables but never changes
existing ones. That held while every change was a new table. The planner is to be
self-hosted (ADR 0020), so people's databases must upgrade in place on every release, and
a column change will come.

## Decision

- **Alembic,** with the migrations inside the package (`character_planner/migrations`) so
  they ship in the image. `alembic.ini` at the repo root is for developers' commands only.
- **The baseline (`0001`) creates only the tables that don't exist yet.** Databases from
  before migrations, made by `create_all` and with no version table, keep their tables and
  data and gain any tables they're missing, such as a copy from before the notification
  tables (#12). So new, current and older databases all reach the same schema by running
  `upgrade head`; nothing has to be stamped by hand.
- **`init_db` runs `upgrade head`** at every start of the API, the worker and the pool
  command, on the app's own connection. It's a no-op when the schema is current.
- **Compose runs a one-off `migrate` service** (`character-planner-db upgrade`) and starts
  the API and the worker only once it has succeeded, so two processes never migrate at
  once.
- **Batch mode** (`render_as_batch`) for SQLite, whose `ALTER TABLE` can't change most
  column properties. It also works on Postgres (#44).
- **A parity test** (`tests/test_migrations.py`) compares the migrated schema with the
  models and fails when a table in `db.py` changes without a migration.

## Consequences

- Changing a table means adding a migration in the same PR:
  `uv run alembic revision --autogenerate -m "…"`, then reading and correcting it,
  because autogenerate can't see renames or data moves.
- Tests run the real migrations for every test database, which adds no noticeable time.
- #14's table changes, #44's Postgres and #61's release notes all build on this.
