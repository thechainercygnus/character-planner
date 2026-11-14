# Contributing

Thanks for your interest. This is a small hobby project with one maintainer, so reviews are
best effort. The rules below keep changes easy to review.

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
[GOVERNANCE.md](GOVERNANCE.md) says who decides what and how decisions are recorded.

## Proposing a change

1. **Open an issue first**, unless the change is a small fix. Say what you want to change
   and why. The [roadmap (#25)](https://github.com/thechainercygnus/character-planner/issues/25)
   shows what's planned and in what order.
2. **One branch per issue**, from an up-to-date `main`: `feature/<issue>-<slug>`, or
   `fix/<slug>` for a small fix without an issue.
3. **Keep changes small.** One concern per commit, with an imperative subject
   ("Add the talents tab", not "Added talents").
4. **Open a pull request.** Write `Closes #<issue>` when it completes the issue, or
   `Refs #<issue>` when it's part of one.
5. **CI must pass** before merging: the `check`, `frontend`, `docker` and `secret-scan`
   jobs. A red job blocks the merge, even when it looks unrelated.

Decisions with lasting consequences get a short, numbered ADR in [`docs/adr/`](docs/adr/).

## Sign off your commits (DCO)

Every commit must be signed off under the [Developer Certificate of
Origin](https://developercertificate.org/). The sign-off says you wrote the change, or
have the right to submit it, under this project's license (AGPL-3.0-or-later).

```
git commit -s
```

This adds a `Signed-off-by: Your Name <you@example.com>` line matching your git identity.
To sign off commits you already made on your branch: `git rebase --signoff main`.

## Tests

- New or changed behaviour comes with tests.
- A bug fix comes with a regression test that fails without the fix.
- Tests never touch the network or read `.env`. External HTTP is mocked with
  [respx](https://lundberg.github.io/respx/) in the backend.
- The Forever API is undocumented. Don't invent response fields: base parsers and test
  fixtures on real responses (see [ADR 0002](docs/adr/0002-raw-snapshots-first.md)).
- A change to a table in `src/character_planner/db.py` needs an Alembic migration in the
  same pull request (see [ADR 0022](docs/adr/0022-schema-migrations.md)).

## Coding standards

CI enforces these, and the pre-commit hooks run them locally:

- **Python** follows [PEP 8](https://peps.python.org/pep-0008/), checked by
  [Ruff](https://docs.astral.sh/ruff/), and is formatted by `ruff format` (Black's style,
  100-character lines). Types are checked by [pyright](https://microsoft.github.io/pyright/),
  strictly for `src/`. Settings are in `pyproject.toml`.
- **TypeScript** is checked by `tsc` in `strict` mode with extra flags
  (`frontend/tsconfig.app.json`), and by [oxlint](https://oxc.rs/docs/guide/usage/linter)'s
  correctness, suspicious and perf rules (`frontend/.oxlintrc.json`). Warnings fail too.
- Never log or print access tokens, the Battle.net client secret or webhook URLs.
- Never commit `.env`, `samples/` or `data/*.db`: they hold secrets or personal data.
- GitHub Actions are pinned to a full commit SHA with the version as a comment, and
  Docker images by tag and digest.

## Setting up and running the checks

You need [uv](https://docs.astral.sh/uv/) and Node.js. Then:

```
uv sync
cd frontend && npm ci && cd ..
uv run pre-commit install
```

The hooks then run on every commit. To run the full check by hand:

```
uv run ruff check --fix && uv run ruff format
uv run pyright
uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test
```

The repository's own [Semgrep](https://semgrep.dev) rules (#57) live in `.semgrep/`, each
with test cases, and run in CI. To run them locally:
`uvx --from semgrep semgrep scan --error --config .semgrep/rules src`.

Coverage is measured in CI and shown in each run's summary (#55). To see it locally:
`uv run pytest --cov` (add `--cov-report=html` for a browsable report in `htmlcov/`), and
`npm run coverage` in `frontend/` (an HTML report lands in `frontend/coverage/`). Both
have a floor (#94), the coverage measured when it was set: `fail_under` in
`pyproject.toml` and `thresholds` in `frontend/vitest.config.ts`. A change that lowers
coverage fails CI, so add tests with new code. When coverage grows, raise the floors.

The [README](README.md) covers running the app; you need a Battle.net API client for
anything that talks to Blizzard, but not for the tests.

## Security issues

Don't open a public issue for a vulnerability. Report it privately as described in
[SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contribution is licensed under the
[AGPL-3.0-or-later](LICENSE), like the rest of the project.
