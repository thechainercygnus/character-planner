# character-planner

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/thechainercygnus/character-planner/badge)](https://scorecard.dev/viewer/?uri=github.com/thechainercygnus/character-planner)
[![Documentation](https://readthedocs.org/projects/character-planner/badge/?version=latest)](https://character-planner.readthedocs.io/)

**Documentation:** [character-planner.readthedocs.io](https://character-planner.readthedocs.io/):
self-hosting, releases, and the decision records.

Planner for a WoW Forever character: pulls data from the Battle.net Profile API, keeps a
history of snapshots, and compares gear against curated targets: per slot, the one to go for
at your level and the ones coming up.

The Forever API is undocumented, so the app stores raw responses and models them only
after seeing real data. See [ADR 0002](docs/adr/0002-raw-snapshots-first.md).

## Setup

1. Create a client at the [Battle.net developer portal](https://develop.battle.net/access/clients)
   (redirect URI `http://localhost:8000/auth/callback` if it asks; syncs don't use the
   login, ADR 0027).
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
| Pull fresh data (no login: the app's own token, ADR 0027) | `POST /api/sync`, or **Sync now** |
| Optional Battle.net login (only the account's character list needs it) | http://localhost:8000/auth/login |
| Character summary (Markdown) | http://localhost:8000/api/summary.md |
| Character / gear plan (JSON) | `/api/character`, `/api/gear` |
| Re-run item lookups | `POST /api/items/refresh?force=true` |
| Build the item pool (dungeon drops + quest rewards) | `uv run character-planner-pool` or `POST /api/pool/refresh` (`?level=N` for one level's window; guest mode offers it) |
| Item pool for your level window (JSON) | `/api/pool` |
| Best upgrades per slot + dungeons worth running | `/api/recommendations` |
| What you can wear and how Upgrades lists items (YAML is the default) | `GET`/`PUT`/`DELETE /api/rules` (or **Upgrades settings** on the Upgrades tab) |
| Edit gear targets (YAML is the default) | `PUT`/`DELETE /api/targets` (or **Edit targets** on the Plan tab) |
| Pin an item as a target | `POST /api/targets/pins`, `DELETE /api/targets/pins/{item_id}` (or **Make target** in an expanded Upgrades row) |
| Never suggest an item | `GET /api/choices`, `PUT`/`DELETE /api/choices/{item_id}` (or **Never suggest**) |
| Guest mode: best items and dungeons for a class and level, no account | `/api/guest`, `/api/guest/recommendations?level=20&class=warrior&faction=alliance` (or the landing page, and **Guest mode** in the ⋯ menu) |
| Version, data credits and the source link shown in the page footer (`SOURCE_URL` points it at a fork) | `/api/about` |
| Progress over time (one point per sync, gear changes, level-ups) | `/api/progress` |
| Talent plan vs synced talents (next point, off-plan points) | `/api/talents`; the trees at `/api/talents/tree`; plan on the talent trees in the Talents tab (ADR 0025); the Character tab shows talents as spent, read-only (#41), default in `data/curated/talent_plan.yaml` |
| Stat weights for scoring | `GET`/`PUT`/`DELETE /api/weights` for the active preset (or the **Stat weights** button on the Upgrades and Plan tabs) |
| Weight presets (Leveling tank, Dungeon tank, Solo DPS, your own) | `PUT /api/weights/active`, `POST /api/weights/presets`, `PATCH`/`DELETE /api/weights/presets/{key}` |
| Alerts in Discord (level-ups, targets, upgrades; failed jobs, upstream errors) | **Alerts** in the status bar, or `/api/notifications` (ADR 0021) |
| API docs | http://localhost:8000/docs |
| Logs (console; files with `LOG_DIR`) | `LOG_LEVEL=DEBUG` for upstream requests, `LOG_DIR=data/logs` for `server.log` and `access.log` (ADR 0019) |
| Run scheduled syncs and pool refreshes | `uv run character-planner-worker` (`--once` to run them now) |

## Run your own

The [self-hosting guide](https://character-planner.readthedocs.io/en/latest/self-hosting.html)
([source](docs/self-hosting.md)) takes you from nothing to your own planner syncing your
character, using the published image. Docker Compose runs the app and the
scheduled worker, optionally served over Tailscale ([ADR 0011](docs/adr/0011-docker-compose-with-a-worker.md)).

## Develop

```
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test
```

CI runs the same checks plus a gitleaks secret scan and a Docker build with a smoke test.
While the app runs, the API docs are at http://localhost:8000/docs (FastAPI's interactive
OpenAPI docs).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): issues first, a branch and pull request per issue,
tests with every change, and signed-off commits (DCO). What's planned next is on the
[roadmap (#25)](https://github.com/thechainercygnus/character-planner/issues/25).

## Security

Please report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## License

Character Planner is free software under the [GNU Affero General Public License v3.0 or
later](LICENSE). You may run, study, share and change it. If you run a modified version
for other people to use over a network, you must offer them its source code under the same
license.

The license covers this project's code only:

- World of Warcraft names, game data and icons belong to Blizzard Entertainment and are
  used under its developer API terms. This project isn't affiliated with Blizzard.
- Item and dungeon data come from [Forever Companion](https://forevercompanion.io), which
  gathers them from ForeverChanges, Wowhead and Zockify. Its attribution terms apply.
