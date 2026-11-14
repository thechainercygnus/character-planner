# CLAUDE.md

Instructions for AI coding agents working in this repo.

## What this is

A single-user planner for a WoW Forever character (Brumboldt Doomlet, Gnome Protection
Warrior, US). It pulls character data from the Battle.net Profile API, stores raw
snapshots, and compares them to hand-curated targets in `data/curated/`.

## Commands

All tooling runs through uv. Run the full check, backend and frontend, before calling any
change done or pushing:

```
uv sync
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test
```

Run the app: `uv run uvicorn character_planner.app:create_app --factory --reload`
Capture real API responses: `uv run character-planner-spike` (needs `.env`, opens a browser).
Probe static item endpoints: `uv run character-planner-probe-items` (app-only token, no browser).
Look up Forever Companion items by id: `uv run character-planner-probe-companion --ids 270200-270260`.
Build the item pool with progress: `uv run character-planner-pool` (first run takes a few minutes).
Frontend (from `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run dev`.
Changed a route or an API model? Regenerate the docs site's API reference: `uv run character-planner-api-docs` (writes `docs/api.md` and `docs/_static/openapi.json`); `tests/test_api_reference.py` fails until they match.
Custom Semgrep rules (#57) in `.semgrep/`: `uvx --from semgrep semgrep --test --config .semgrep/rules .semgrep/tests` tests them, and `uvx --from semgrep semgrep scan --error --config .semgrep/rules src` runs them, as CI's `semgrep` workflow does.
Coverage (#55): `uv run pytest --cov`; `npm run coverage` in `frontend/`. CI puts both in the run's summary and fails below the floors (#94): `fail_under` in `pyproject.toml`, `thresholds` in `frontend/vitest.config.ts`. Raise them when coverage grows; never lower them to pass.
Run scheduled jobs once: `uv run character-planner-worker --once` (sync, then pool refresh).
Changed a table in `db.py`? Add a migration in the same PR: `uv run alembic revision --autogenerate -m "..."`, then read and correct it (ADR 0022). `tests/test_migrations.py` fails until it matches. `uv run character-planner-db current` shows the schema version.
Deploy (Docker): `docker compose up -d --build`; over Tailscale add `-f compose.tailscale.yaml`. See `docs/self-hosting.md`.
Docs site (Read the Docs, `.readthedocs.yaml`): `uv run --group docs sphinx-build -W -b html docs docs/_build/html`. Warnings fail the build, as in CI.
Release: bump `pyproject.toml`'s version in a PR, then the user tags `vX.Y.Z` on `main`; `release.yml` publishes to GHCR (ADR 0026, `docs/releasing.md`). Tagging is the user's call, like merging.

## Rules

`CONTRIBUTING.md` holds the shared rules for everyone (workflow, tests, coding standards,
DCO sign-off). The rules here add what agents need on top.

- The Forever API is undocumented. Never invent a response field: read it from a real
  sample in `samples/` or a fixture in `tests/fixtures/`, and say when you're assuming.
  See `docs/adr/0002-raw-snapshots-first.md`.
- Every behaviour change gets a test. External HTTP is mocked with respx; tests never
  hit the network or read `.env`.
- Never commit `.env`, `samples/` or `data/*.db`: they hold secrets or personal data.
- Pin GitHub Actions to a full commit SHA with the version as a comment (`uses: owner/action@<sha> # v1.2.3`), and Docker images by tag and digest. Give each workflow job only the permissions it needs. Dependabot keeps pins current.
- Check a third-party API against its vendored spec (`docs/vendor/`) before concluding it's broken.
- Never log or print access tokens or the client secret.
- Record decisions with lasting consequences as a new ADR in `docs/adr/`, numbered,
  short and terse.
- Keep changes small and on a branch; one concern per commit, imperative commit subjects.

## Workflow

- One branch per issue, named `feature/<issue>-<slug>` (or `fix/<slug>` for small fixes
  without an issue). Branch from an up-to-date `main`. Never commit or push to `main`.
- Open a pull request for every branch. Use `Closes #<issue>` when it completes the issue
  and `Refs #<issue>` when it's part of one.
- CI must pass before merging: the `check`, `frontend`, `docker` and `secret-scan` jobs. A red
  job is a blocker, even if it looks unrelated; fix it or say why in the PR.
- Remote Control sessions run in their own git worktree. Stay inside it: don't edit
  files in another checkout of this repo.
- Commits and pushes need the user's go-ahead. Stop at a ready-to-review PR; the user
  merges.

## Roadmap

Issue #25 (label `roadmap`) is the work order. Read it before choosing what to do next,
and keep it true as you go: edit its body with `gh issue edit 25 --body-file <file>`.

- Pick the first unchecked item under "Now" or "Next" that isn't parked or marked as the
  user's own task.
- When you open a PR for an item, note the PR number on its line. When it merges, check
  the box and say what's left, if anything, before the issue can close.
- When an issue closes, move its line to "Done".
- New issues go on the roadmap in the right place, with a one-line reason if it isn't the end.
- Reorder only when the user asks, or propose a change and wait for their answer.
- Keep the existing sections and their order. Write each item as `#<n> <title>` plus a
  short note. Don't change items you didn't work on.

## Layout

- `src/character_planner/blizzard/`: OAuth and the API client (raw JSON in, status always reported)
- `src/character_planner/db.py`: SQLModel tables (`Character`, `Snapshot`, `StoredToken`...); `init_db` runs the migrations in `migrations/` (ADR 0022)
- `src/character_planner/characters.py`: tracked characters; `.env` seeds the first, which adopts rows from before #14; snapshots, progress history and the settings edited in the app belong to one, and every reader takes a `character_id`; `db.owned`/`save_owned` read and write a character's settings row; a request picks its character with the `X-Character-Id` header, else the first (ADR 0036)
- `src/character_planner/classes.py` + `data/curated/classes/*.yaml`: shipped defaults per class, chosen by the synced class; the Warrior's are the original curated files (ADR 0023)
- `src/character_planner/curated.py` + `data/curated/*.yaml`: hand-maintained defaults (targets, stat weights, rules); edits made in the app live in the database
- `src/character_planner/scoring.py`: gear scores from editable stat weights (ADR 0005) in named presets (ADR 0013); shipped presets in `data/curated/stat_weights.yaml` and `weight_presets.yaml`
- `src/character_planner/items.py`: item catalog (Battle.net item search + icons), cached in SQLite (ADR 0003)
- `src/character_planner/companion.py`: Forever Companion source, GET /items/{id} only (ADR 0004); spec in `docs/vendor/`
- `src/character_planner/dungeons.py`: Forever Companion dungeons: drop tables and quest rewards (ADR 0006)
- `src/character_planner/pool.py`: item pool built from dungeon data, level window, target id resolution (ADR 0006)
- `src/character_planner/rares.py`: rares and their drops, a third pool source; merged by id because the list's cache ignores filters (ADR 0029)
- `src/character_planner/crafting.py` + `data/curated/professions.yaml`: profession ranks and crafted gear from known recipes, a pool source (ADR 0031)
- `src/character_planner/lookahead.py`: what the next levels bring, built from the gear, talent, class quest, profession and dungeon views (ADR 0032)
- `src/character_planner/class_quests.py`: the class quest checklist by class, faction, race and level; done marks set in the app (ADR 0030)
- `src/character_planner/quests.py`: quest chains for quest rewards; steps no dungeon describes fetched by id, zone quests only named (ADR 0028)
- `src/character_planner/retention.py`: Blizzard data kept at most 30 days: pruning, refresh-before-expiry ages, archived Progress points, forgetting a character Battle.net no longer has (ADR 0034, #131)
- `src/character_planner/progress.py`: progress over time rebuilt from snapshots: points, gear changes, level-ups (ADR 0008)
- `src/character_planner/talents.py`: the talent plan compared with synced talents (ADR 0009), matched by talent id; default in `data/curated/talent_plan.yaml`
- `src/character_planner/talent_trees.py`: Forever's talent trees from Blizzard's game data, and the plan rules (prerequisites, points per row); the frontend's twin is `frontend/src/talentRules.ts` (ADR 0025)
- `src/character_planner/enchants.py`: enchant catalog from Blizzard recipe data and per-slot enchant advice (ADR 0010); gaps filled in `data/curated/enchants.yaml`
- `src/character_planner/recommend.py`: best upgrades per slot and dungeons worth running, from the pool (ADR 0007)
- `src/character_planner/enchant_corrections.py`: corrections to `enchants.yaml` made in the app (material levels, crafted effects, per_slot), applied in `get_enchant_data` (ADR 0033)
- `src/character_planner/rules.py`: the Upgrades rules edited in the app; `data/curated/recommend.yaml` is the default (ADR 0016)
- `src/character_planner/guest.py`: guest mode, recommendations for a class and level from the shipped defaults; reads no character data, stores nothing (ADR 0017)
- `src/character_planner/erase.py`: deletes everything stored for the character, from the Privacy page or `character-planner-db erase --yes`; every table but the shared game-data caches in `SHARED` (#133, ADR 0034)
- `src/character_planner/users.py`: users, server-side sessions and per-user tokens when `PLANNER_USERS` is on; the first sign-in is the admin; characters belong to a user and requests resolve them through the signed-in user (#16, ADR 0037)
- `src/character_planner/account.py`: the signed-in account's characters (`/profile/user/wow`), to pick ones to track; fetched each time, never stored (#15, ADR 0036)
- `src/character_planner/choices.py`: items dismissed in the app, on top of `exclude_item_ids` (ADR 0012)
- `src/character_planner/targets.py`: gear targets edited in the app and pins from the Upgrades tab; `gear_targets.yaml` is the default (ADR 0014); per-target levels (ADR 0015)
- `src/character_planner/fields.py`: defensive JSON readers used by all parsers
- `src/character_planner/views.py`: the only code that reads API response shapes; typed views for the frontend
- `src/character_planner/summary.py`: Markdown rendering of those views, for pasting into a chat
- `src/character_planner/notify.py`: alerts to Discord webhooks: destinations, change detection after a sync, an outbox the worker sends (ADR 0021)
- `src/character_planner/logs.py`: logging for the API and the worker: console, rotating files with `LOG_DIR`, request ids, redaction of secrets in every line (ADR 0019)
- `src/character_planner/tokens.py`: the app's own Battle.net token (Client Credentials), cached and renewed; syncs and every refresh use it, so no login is needed (ADR 0027)
- `src/character_planner/leases.py`: one-at-a-time leases for long refreshes, shared by the API and the worker (ADR 0024)
- `src/character_planner/jobs.py`: sync and pool refresh, shared by the API and the worker
- `src/character_planner/worker.py`: scheduled jobs beside the API (ADR 0011); `Dockerfile`, `compose*.yaml` and `docs/self-hosting.md` deploy both
- `src/character_planner/app.py`: FastAPI routes, built by `create_app()`. Data routes live under `/api`, the optional Battle.net login under `/auth`; a built frontend in `frontend/dist` is served at `/`
