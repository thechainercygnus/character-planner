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
Frontend (from `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run dev`. Browser checks (#153, #165): `npm run e2e` builds the app and checks it in Chromium, the API mocked from `e2e/api-fixtures.json` through `e2e/support.ts`: phone layout, every dialog fitting, the main flows, and axe on every tab and dialog, failing on any finding (first time: `npx playwright install chromium`); CI's frontend job runs it.
The README's and docs site's screenshot (#252): `npm run screenshot` in `frontend/` retakes `docs/_static/planner-upgrades.webp` from the same fixtures (the Upgrades tab, 2x, WebP); rerun it after a visible UI change.
Changed a route or an API model? Regenerate the docs site's API reference: `uv run character-planner-api-docs` (writes `docs/api.md` and `docs/_static/openapi.json`); `tests/test_api_reference.py` fails until they match.
Custom Semgrep rules (#57) in `.semgrep/`: `uvx --from semgrep semgrep --test --config .semgrep/rules .semgrep/tests` tests them, and `uvx --from semgrep semgrep scan --error --config .semgrep/rules src` runs them, as CI's `semgrep` workflow does.
Coverage (#55): `uv run pytest --cov`; `npm run coverage` in `frontend/`. CI puts both in the run's summary and fails below the floors (#94): `fail_under` in `pyproject.toml`, `thresholds` in `frontend/vitest.config.ts`. Raise them when coverage grows; never lower them to pass.
Backups (#240, ADR 0061): `uv run character-planner-db backup` backs up now (needs `BACKUP_S3_*` and `BACKUP_AGE_RECIPIENT`); `uv run character-planner-db restore --file backup.json.gz --yes` restores a decrypted one into an empty database.
Delete one user and their data (users on, #16): `uv run character-planner-db delete-user ACCOUNT_ID --yes`.
Background jobs (#17, ADR 0039): with `REDIS_URL` set, Syncs are queued; `uv run character-planner-jobs` works the queue (the worker container runs it as a child). Tests use fakeredis.
Run the tests on Postgres too (#44): `TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest` (each test gets its own schema), as CI's `postgres` job does. Move a database: `COPY_TO_DATABASE_URL=... uv run character-planner-db copy-to`.
Run scheduled jobs once: `uv run character-planner-worker --once` (sync, then pool refresh).
Changed a table in `db.py`? Add a migration in the same PR: `uv run alembic revision --autogenerate -m "..."`, then read and correct it (ADR 0022). `tests/test_migrations.py` fails until it matches. `uv run character-planner-db current` shows the schema version.
Deploy (Docker): `docker compose up -d --build`; over Tailscale add `-f compose.tailscale.yaml`; on Postgres add `-f compose.postgres.yaml` (ADR 0038). Local test builds must set their own `PLANNER_IMAGE`, or they overwrite the `.env`'s image tag. See `docs/self-hosting.md`.
Docs site (Read the Docs, `.readthedocs.yaml`): `uv run --group docs sphinx-build -W -b html docs docs/_build/html`. Warnings fail the build, as in CI.
Release: bump `pyproject.toml`'s version in a PR, then the user tags `vX.Y.Z` on `main`; `release.yml` publishes to GHCR (ADR 0026, `docs/releasing.md`). Tagging is the user's call, like merging. Each minor or major release starts `release/X.Y` from its tag and retires the previous one; patches are backported there by PR, tagged there, then merged back into `main` (ADR 0050).

Project skills in `.claude/skills/` (Claude Code loads them): `ship-pr` takes finished work to a ready PR and watches its CI, `roadmap` edits #25 through `roadmap.py` (a diff first, `--save` to write), `cut-rc` tags a test release when Bryce asks, `stack-debug` looks into a running stack read-only, `layout-probe` measures and fixes layout bugs with Playwright, and `change-checklist` lists what each kind of change must also touch.

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
  without an issue). Branch from an up-to-date `main`, or from `release/X.Y` for a patch to the
  current release (milestone `vX.Y.Z`, Z above 0; ADR 0050). Never commit or push to `main` or `release/*`.
- Before opening a pull request, and before pushing more commits to an open one: fetch
  `main`, merge `origin/main` into the branch, resolve any conflicts, and rerun the full
  checks on the merged result. This catches conflicts and gaps between PRs (a test from
  one PR that another's files must pass) before review. If the remote branch has commits
  you don't (an "Update branch" on GitHub), build on them; never force-push.
- Open a pull request for every branch. Use `Closes #<issue>` when it completes the issue
  and `Refs #<issue>` when it's part of one.
- CI must pass before merging: the `check`, `frontend`, `docker`, `postgres` and `secret-scan` jobs. A red
  job is a blocker, even if it looks unrelated; fix it or say why in the PR.
- Remote Control sessions run in their own git worktree. Stay inside it: don't edit
  files in another checkout of this repo.
- Commits and pushes need the user's go-ahead. Stop at a ready-to-review PR; the user
  merges.

## Roadmap

Issue #25 (label `roadmap`) is the work order. Read it before choosing what to do next,
and keep it true as you go: edit its body with the `roadmap` skill's script, or `gh issue edit 25 --body-file <file>`.

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

The full module map, one line per file with its issue and ADR, is in
`docs/architecture.md` under **Modules**: grep it for the file or feature you're touching.
What holds everywhere:

- Python in `src/character_planner/`, one module per feature; routes in `app.py`
  (`create_app()`), data under `/api`, the login under `/auth`, the built frontend at `/`.
- Tables in `db.py`, migrations in `migrations/`. Shipped defaults in `data/curated/`;
  edits made in the app live in the database.
- `views.py` is the only code that reads API response shapes, through `fields.py`'s
  defensive readers. Every Battle.net and Forever Companion client comes from
  `upstream.client()`. Wowhead links are built only in `links.py`.
- Per-character data: every reader takes a `character_id`; a request picks one with
  `X-Character-Id` (ADR 0036). Routes check a permission by name through
  `app.ROUTE_PERMISSIONS`, never a role (ADR 0055).
- `addon/SCHEMA.md` is the contract with the CharacterPlannerExport addon, which lives in
  `thechainercygnus/character-planner-export` with its issues (ADR 0051). Its Lua is
  Bryce's learning work: review and explain it when asked, don't write it.
