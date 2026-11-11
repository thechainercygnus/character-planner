# character-planner

Planner for a WoW Forever character: pulls data from the Battle.net Profile API, keeps a
history of snapshots, and compares gear against curated targets for each level bracket.

The Forever API is undocumented, so the app stores raw responses and models them only
after seeing real data. See [ADR 0002](docs/adr/0002-raw-snapshots-first.md).

## Setup

1. Create a client at the [Battle.net developer portal](https://develop.battle.net/access/clients)
   with redirect URI `http://localhost:8000/auth/callback`.
2. `cp .env.example .env` and fill in the client ID and secret.
3. `uv sync`
4. `uv run pre-commit install`

## Use

| Step | Command / URL |
|---|---|
| Capture raw API responses (phase 0) | `uv run character-planner-spike` |
| Run the app | `uv run uvicorn character_planner.app:create_app --factory --reload` |
| Log in | http://localhost:8000/auth/login |
| Pull fresh data | `POST /api/sync` |
| Character summary (Markdown) | http://localhost:8000/api/summary.md |
| Character / gear plan (JSON) | `/api/character`, `/api/gear` |
| Re-run item lookups | `POST /api/items/refresh?force=true` |
| API docs | http://localhost:8000/docs |

## Develop

```
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
```

CI runs the same checks plus a gitleaks secret scan.
