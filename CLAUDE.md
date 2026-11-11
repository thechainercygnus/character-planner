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

## Rules

- The Forever API is undocumented. Never invent a response field: read it from a real
  sample in `samples/` or a fixture in `tests/fixtures/`, and say when you're assuming.
  See `docs/adr/0002-raw-snapshots-first.md`.
- Every behaviour change gets a test. External HTTP is mocked with respx; tests never
  hit the network or read `.env`.
- Never commit `.env`, `samples/` or `data/*.db`: they hold secrets or personal data.
- Never log or print access tokens or the client secret.
- Record decisions with lasting consequences as a new ADR in `docs/adr/`, numbered,
  short and terse.
- Keep changes small and on a branch; one concern per commit, imperative commit subjects.

## Layout

- `src/character_planner/blizzard/`: OAuth and the API client (raw JSON in, status always reported)
- `src/character_planner/db.py`: SQLModel tables (`Snapshot`, `StoredToken`)
- `src/character_planner/curated.py` + `data/curated/*.yaml`: hand-maintained targets
- `src/character_planner/views.py`: the only code that reads API response shapes; typed views for the frontend
- `src/character_planner/summary.py`: Markdown rendering of those views, for pasting into a chat
- `src/character_planner/app.py`: FastAPI routes, built by `create_app()`. Data routes live under `/api`, login under `/auth`; a built frontend in `frontend/dist` is served at `/`
