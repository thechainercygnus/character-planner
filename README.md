# character-planner

Planner for a WoW Forever character: pulls data from the Battle.net Profile API, keeps a
history of snapshots, and compares gear against curated targets: per slot, the one to go for
at your level and the ones coming up.

The Forever API is undocumented, so the app stores raw responses and models them only
after seeing real data. See [ADR 0002](docs/adr/0002-raw-snapshots-first.md).

## Setup

1. Create a client at the [Battle.net developer portal](https://develop.battle.net/access/clients)
   with redirect URI `http://localhost:8000/auth/callback`.
2. `cp .env.example .env` and fill in the client ID and secret.
3. `uv sync`
4. `cd frontend && npm ci` (the frontend's tools, also used by the pre-commit hooks)
5. `uv run pre-commit install`: every commit then runs ruff, pyright and pytest, and the
   frontend's lint, typecheck and tests when frontend files change.

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
| Build the item pool (dungeon drops + quest rewards) | `uv run character-planner-pool` or `POST /api/pool/refresh` |
| Item pool for your level window (JSON) | `/api/pool` |
| Best upgrades per slot + dungeons worth running | `/api/recommendations` |
| What you can wear and how Upgrades lists items (YAML is the default) | `GET`/`PUT`/`DELETE /api/rules` (or **Upgrades settings** on the Upgrades tab) |
| Edit gear targets (YAML is the default) | `PUT`/`DELETE /api/targets` (or **Edit targets** on the Plan tab) |
| Pin an item as a target | `POST /api/targets/pins`, `DELETE /api/targets/pins/{item_id}` (or **Make target** in an expanded Upgrades row) |
| Never suggest an item | `GET /api/choices`, `PUT`/`DELETE /api/choices/{item_id}` (or **Never suggest**) |
| Guest mode: best items and dungeons for a class and level, no account | `/api/guest`, `/api/guest/recommendations?level=20&class=warrior&faction=alliance` (or the landing page, and **Guest mode** in the ⋯ menu) |
| Progress over time (one point per sync, gear changes, level-ups) | `/api/progress` |
| Talent plan vs synced talents (next point, off-plan points) | `/api/talents`, plan in `data/curated/talent_plan.yaml` or edit it in the app |
| Stat weights for scoring | `GET`/`PUT`/`DELETE /api/weights` for the active preset (or the **Stat weights** button on the Upgrades and Plan tabs) |
| Weight presets (Leveling tank, Dungeon tank, Solo DPS, your own) | `PUT /api/weights/active`, `POST /api/weights/presets`, `PATCH`/`DELETE /api/weights/presets/{key}` |
| API docs | http://localhost:8000/docs |
| Run scheduled syncs and pool refreshes | `uv run character-planner-worker` (`--once` to run them now) |

## Deploy

Docker compose runs the app and the scheduled worker, optionally served over Tailscale.
See [docs/deploy.md](docs/deploy.md) and [ADR 0011](docs/adr/0011-docker-compose-with-a-worker.md).

## Develop

```
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
```

CI runs the same checks plus a gitleaks secret scan and a Docker build with a smoke test.
