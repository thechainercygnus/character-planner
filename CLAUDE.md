# CLAUDE.md

Instructions for AI coding agents working in this repo.

## What this is

A single-user planner for a WoW Forever character (Brumboldt Doomlet, Gnome Protection
Warrior, US). It pulls character data from the Battle.net Profile API, stores raw
snapshots, and compares them to hand-curated targets in `data/curated/`.

## Commands

All tooling runs through uv. Run the full check before calling any change done:

```
uv sync
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
```

Run the app: `uv run uvicorn character_planner.app:create_app --factory --reload`
Capture real API responses: `uv run character-planner-spike` (needs `.env`, opens a browser).
Probe static item endpoints: `uv run character-planner-probe-items` (app-only token, no browser).
Look up Forever Companion items by id: `uv run character-planner-probe-companion --ids 270200-270260`.
Build the item pool with progress: `uv run character-planner-pool` (first run takes a few minutes).
Frontend (from `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run dev`.

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

## Layout

- `src/character_planner/blizzard/`: OAuth and the API client (raw JSON in, status always reported)
- `src/character_planner/db.py`: SQLModel tables (`Snapshot`, `StoredToken`)
- `src/character_planner/curated.py` + `data/curated/*.yaml`: hand-maintained targets and default stat weights
- `src/character_planner/scoring.py`: gear scores from editable stat weights (ADR 0005)
- `src/character_planner/items.py`: item catalog (Battle.net item search + icons), cached in SQLite (ADR 0003)
- `src/character_planner/companion.py`: Forever Companion source, GET /items/{id} only (ADR 0004); spec in `docs/vendor/`
- `src/character_planner/dungeons.py`: Forever Companion dungeons: drop tables and quest rewards (ADR 0006)
- `src/character_planner/pool.py`: item pool built from dungeon data, level window, target id resolution (ADR 0006)
- `src/character_planner/progress.py`: progress over time rebuilt from snapshots: points, gear changes, level-ups (ADR 0008)
- `src/character_planner/recommend.py`: best upgrades per slot and dungeons worth running, from the pool (ADR 0007); rules in `data/curated/recommend.yaml`
- `src/character_planner/fields.py`: defensive JSON readers used by all parsers
- `src/character_planner/views.py`: the only code that reads API response shapes; typed views for the frontend
- `src/character_planner/summary.py`: Markdown rendering of those views, for pasting into a chat
- `src/character_planner/app.py`: FastAPI routes, built by `create_app()`. Data routes live under `/api`, login under `/auth`; a built frontend in `frontend/dist` is served at `/`
