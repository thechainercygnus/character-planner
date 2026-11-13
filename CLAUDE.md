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
Run scheduled jobs once: `uv run character-planner-worker --once` (sync, then pool refresh).
Deploy (Docker): `docker compose up -d --build`; over Tailscale add `-f compose.tailscale.yaml`. See `docs/deploy.md`.

## Rules

- The Forever API is undocumented. Never invent a response field: read it from a real
  sample in `samples/` or a fixture in `tests/fixtures/`, and say when you're assuming.
  See `docs/adr/0002-raw-snapshots-first.md`.
- Every behaviour change gets a test. External HTTP is mocked with respx; tests never
  hit the network or read `.env`.
- Never commit `.env`, `samples/` or `data/*.db`: they hold secrets or personal data.
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
- `src/character_planner/db.py`: SQLModel tables (`Snapshot`, `StoredToken`)
- `src/character_planner/curated.py` + `data/curated/*.yaml`: hand-maintained defaults (targets, stat weights, rules); edits made in the app live in the database
- `src/character_planner/scoring.py`: gear scores from editable stat weights (ADR 0005) in named presets (ADR 0013); shipped presets in `data/curated/stat_weights.yaml` and `weight_presets.yaml`
- `src/character_planner/items.py`: item catalog (Battle.net item search + icons), cached in SQLite (ADR 0003)
- `src/character_planner/companion.py`: Forever Companion source, GET /items/{id} only (ADR 0004); spec in `docs/vendor/`
- `src/character_planner/dungeons.py`: Forever Companion dungeons: drop tables and quest rewards (ADR 0006)
- `src/character_planner/pool.py`: item pool built from dungeon data, level window, target id resolution (ADR 0006)
- `src/character_planner/progress.py`: progress over time rebuilt from snapshots: points, gear changes, level-ups (ADR 0008)
- `src/character_planner/talents.py`: hand-entered talent plan compared with synced talents (ADR 0009); default in `data/curated/talent_plan.yaml`
- `src/character_planner/enchants.py`: enchant catalog from Blizzard recipe data and per-slot enchant advice (ADR 0010); gaps filled in `data/curated/enchants.yaml`
- `src/character_planner/recommend.py`: best upgrades per slot and dungeons worth running, from the pool (ADR 0007)
- `src/character_planner/rules.py`: the Upgrades rules edited in the app; `data/curated/recommend.yaml` is the default (ADR 0016)
- `src/character_planner/guest.py`: guest mode, recommendations for a class and level from the shipped defaults; reads no character data, stores nothing (ADR 0017)
- `src/character_planner/choices.py`: items dismissed in the app, on top of `exclude_item_ids` (ADR 0012)
- `src/character_planner/targets.py`: gear targets edited in the app and pins from the Upgrades tab; `gear_targets.yaml` is the default (ADR 0014); per-target levels (ADR 0015)
- `src/character_planner/fields.py`: defensive JSON readers used by all parsers
- `src/character_planner/views.py`: the only code that reads API response shapes; typed views for the frontend
- `src/character_planner/summary.py`: Markdown rendering of those views, for pasting into a chat
- `src/character_planner/logs.py`: logging for the API and the worker: console, rotating files with `LOG_DIR`, request ids, redaction of secrets in every line (ADR 0019)
- `src/character_planner/jobs.py`: sync and pool refresh, shared by the API and the worker
- `src/character_planner/worker.py`: scheduled jobs beside the API (ADR 0011); `Dockerfile`, `compose*.yaml` and `docs/deploy.md` deploy both
- `src/character_planner/app.py`: FastAPI routes, built by `create_app()`. Data routes live under `/api`, login under `/auth`; a built frontend in `frontend/dist` is served at `/`
