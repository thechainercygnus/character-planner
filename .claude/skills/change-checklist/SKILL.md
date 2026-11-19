---
name: change-checklist
description: What else a change to this repo has to touch, by kind of change. A new API route, table or column, setting, stored data from Blizzard, a module, or something users see. Use while planning or before shipping a change, so the privacy notice, migrations, route sweep, docs and the rest aren't found missing in review or CI.
---

# Change checklist

Find each kind of change you're making, and do every line. The tests named are the ones
that fail when a line is missed.

## A new or changed API route (`app.py`)
- **Scope it:** routes about a character take `CharacterIdDep`. A route about the
  signed-in user takes `UserIdDep` and filters by it. An instance-wide route gets a
  permission in `app.ROUTE_PERMISSIONS`. A new permission goes in `roles.PERMISSIONS`,
  plus a migration adding it to the roles that should have it (ADR 0055). Never check a
  role. Another user's row answers **404**, not 403.
- **Unscoped routes:** classify them in `UNSCOPED` in `tests/test_users.py` (public, own,
  admin or shared), with a comment saying where they're tested.
  `test_every_route_keeps_users_apart` fails until you do.
- **`/auth/*` routes** aren't behind the sign-in middleware: check the session in the
  route.
- **A state-changing route** needs the `X-Requested-With` header (#124). The web app's
  `request()` already sends it.
- **Reference docs:** run `uv run character-planner-api-docs` and commit `docs/api.md`
  and `docs/_static/openapi.json`, or `tests/test_api_reference.py` fails.
- **Frontend:** add the types and calls to `frontend/src/api.ts`. The component tests
  stub `fetch`. Add the route to `frontend/e2e/api-fixtures.json` if a page loads it.

## A new table or column (`db.py`)
- **Migration:** write it by hand in `migrations/versions/`, with the next number and
  date. Use `batch_alter_table` for SQLite, and mark data steps in the docstring.
  `tests/test_migrations.py` must pass.
- **Test data steps** by upgrading to the previous revision, inserting rows, then running
  `init_db`, as in `tests/test_own_webhooks.py`.
- **Per character:** the model gets a `character_id` FK and goes in `characters.OWNED`.
  Read and write it with `db.owned` and `save_owned`.
- **Per user:** a `user_id`. Deletion goes in `users.delete_user`, inside its one
  transaction, with no commit in a helper. The first sign-in adopts rows from before
  users (`users.sign_in`).
- **Erase:** every table is erased by default. Shared game data goes in `erase.SHARED`
  (`tests/test_erase.py`).
- **Data from Blizzard:** it's kept at most 30 days. A cache goes in `retention.CACHES`,
  with a `fetched_at`.
- **Secrets** (tokens, webhook URLs): never logged or returned in full. Store a hash
  where you can.
- **Postgres:** CI's `postgres` job runs every test there. Watch for FK order on delete
  (children first), booleans in raw SQL, and quoting `"user"`.

## A new setting (`config.py`)
- **Validate** anything shown as a link or used in a path or URL (`field_validator`). A
  secret is a `SecretStr`.
- **Document it** in `.env.example` (commented out, with the issue and ADR) and in
  `docs/self-hosting.md`.
- **Compose and Portainer:** if the containers need it, add it to `compose*.yaml` and
  `deploy/portainer.yaml` (`tests/test_deploy_files.py`).
- **Tests:** add a validator test in `tests/test_config.py` or the feature's own tests.
  Tests never read `.env`.

## Something that stores or shows personal data
- **Privacy notice:** update both copies, `docs/privacy.md` and
  `frontend/src/components/Privacy.tsx`. Say what's stored, who can see it, and how it's
  deleted.
- **Users on:** who else sees it? Opt-in only (ADR 0042). Add a test with two users.

## A new module, or a lasting decision
- **ADR:** add one in `docs/adr/`, numbered, short and terse. The docs build picks it up.
  Bryce's choices go in as "Bryce chose ... (date)".
- **CLAUDE.md:** add a line to **Layout** for a new module.
- **`docs/architecture.md`:** update it if the picture changes (a new service, an outside
  API).

## Upstream APIs
- **The Forever API is undocumented:** read field names from `samples/` or
  `tests/fixtures/`, never invent one, and say when you're assuming.
- **Every client** comes from `upstream.client()` (the shared budget, ADR 0040). Tests
  mock HTTP with respx.
- **Check vendored specs** in `docs/vendor/` before calling an API broken.

## Something users see
- **Unit tests:** a component test with `fetch` stubbed (`vitest`).
- **Layout:** if it could, `npm run e2e`; dialogs are checked in `e2e/dialogs.spec.ts`.
  Use `layout-probe` for problems.
- **Copy:** plain wording. Bryce sometimes rewords user-facing text: keep strings easy to
  find.

Then ship it with `ship-pr`.
