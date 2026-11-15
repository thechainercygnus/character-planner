---
name: ship-pr
description: Take finished work on a branch to a ready-to-review PR in this repo. Merge main, run the checks the change needs, commit with the sign-off and attribution, push, open the PR with its milestone, note it on the roadmap, then watch CI and fix what fails. Use whenever a change is done and needs to go up, or more commits go onto an open PR.
---

# Ship a PR

CLAUDE.md's **Workflow** applies throughout:
- **Branch:** one branch per issue (`feature/<n>-<slug>`, or `fix/<slug>`), never `main`.
- **Commits:** one concern each, with an imperative subject.
- **Go-ahead:** commits and pushes need Bryce's. "Proceed", "go ahead" or "continue" on
  the task counts. Stop at a ready PR: Bryce merges.

## 1. Merge main first
```bash
git fetch origin main && git merge origin/main
```
Resolve any conflicts. If the remote branch has commits you don't have (an "Update branch"
on GitHub), pull and build on them. Never force-push.

## 2. Run the checks the change needs
Check what changed with `git diff --name-only origin/main...` plus the uncommitted files.

| Changed | Run |
|---|---|
| `src/`, `tests/`, `pyproject.toml`, `.claude/skills/**/*.py` | `uv run ruff check --fix && uv run ruff format`, `uv run pyright`, `uv run pytest -q --cov` (the floor is in `pyproject.toml`) |
| `src/` | `uvx --from semgrep semgrep scan --error --config .semgrep/rules src` |
| `.semgrep/` | `uvx --from semgrep semgrep --test --config .semgrep/rules .semgrep/tests`, plus the scan |
| A route or an API model | `uv run character-planner-api-docs`, and commit `docs/api.md` and `docs/_static/openapi.json` |
| A table in `db.py` | A migration in the same PR. Write it by hand, like `migrations/versions/*` (`batch_alter_table` for SQLite). `tests/test_migrations.py` must pass. Test any data step. |
| `frontend/` | `npm run lint`, `npm run typecheck`, `npm run coverage`, in `frontend/` |
| `frontend/src/**/*.css`, the layout, `frontend/e2e/` | `npm run e2e` |
| `docs/`, an ADR | `uv run --group docs sphinx-build -W -q -b html docs docs/_build/html` |
| `.github/workflows/` | Actions pinned to a full SHA with `# vX.Y.Z`, and least-privilege `permissions:` |

When unsure, run everything: `uv sync`, then all the backend and frontend commands
above. A new route also goes in `UNSCOPED` in `tests/test_users.py`, or is scoped to the
user.

Prettier: format only the files you created or rewrote, with `npx prettier --single-quote
--no-semi --print-width 120 --write <files>`. Many files predate it, so leave those alone.

## 3. Commit
Write the message to a file in the scratchpad and commit with `git commit -F <file>`.
Never skip the hooks: they rerun the checks.
```
<Imperative subject, under ~70 chars>

<Why, then what, wrapped at 72.>

Closes #<n>        (or Refs #<n>; leave it out for a fix with no issue)

Signed-off-by: <git config user.name> <<git config user.email>>
<the attribution line the session's system reminder gives for commits>
```
The DCO sign-off is required (CONTRIBUTING.md). Take the attribution text from the
current system reminder; don't copy it from an old commit.

## 4. Push and open the PR
```bash
git push -u origin <branch>
gh issue view <n> --json milestone --jq .milestone.title   # the PR takes the issue's milestone
gh pr create --base main --title "<title>" --body-file <file> --milestone <milestone>
```
There's no PR template. Bodies follow this shape:
```
Closes #<n>   (or Refs #<n>)

<One or two sentences: the problem and the result.>

## What changes
- **<Area>:** <what changes>

## Tests
- **<file or suite>:** <what it proves>

## Checks
- **<suite>:** <results>, with test counts
- **Merged `main` first.**
- **Not tested:** <anything only Bryce can check>

<the attribution line the session's system reminder gives for PR bodies>
```
Then use the `ccd_pr` tools: `get_status`, and `bind_pr` if the PR isn't bound.

## 5. Note it on the roadmap
Use the `roadmap` skill: `note <issue> "PR #<n>."`, then add `--save`.

## 6. Watch CI and fix what fails
```bash
gh pr checks <n> --watch --interval 30 >/dev/null 2>&1; gh pr checks <n>
```
For a failing job, read its log:
```bash
gh api repos/thechainercygnus/character-planner/actions/jobs/<job id>/logs | grep -E "Error|Expected|Received|›"
```
The job id is the last number in the check's link. For CodeQL or Semgrep alerts, which
fail the check but don't show in the log:
```bash
gh api "repos/thechainercygnus/character-planner/code-scanning/alerts?ref=refs/pull/<n>/merge&state=open" \
  --jq '.[] | {rule: .rule.id, path: .most_recent_instance.location.path, line: .most_recent_instance.location.start_line, msg: .most_recent_instance.message.text}'
```
Failures seen before:
- **Linux fonts:** CI's fonts are wider than Windows'. Layout checks that pass locally can
  overflow there. Reproduce by widening text with `page.addStyleTag`.
- **Playwright and the runner:** the runner's Ubuntu needs a recent Playwright. Look up
  the current release before pinning one.
- **The Semgrep secrets rule** follows taint through calls. Fix the code, or narrow the
  rule with a test in `.semgrep/tests`. Never disable it.
- **CodeQL** flags deliberate leaks in test fixtures when the source is named like a
  secret. Rename or restructure the fixture rather than dismissing the alert.

Fix on the branch, rerun step 2, merge `main` again, and push. Report what failed and
what fixed it.

## Windows shell
- **Heredocs:** they break on `'''`, `${...:-` and some quotes. Write scripts with the
  Write tool and run them; edit files with the Edit tool.
- **Line endings:** Python's `write_text` writes CRLF on Windows. Use `write_bytes` when
  LF matters (issue bodies, fixtures).
- **Paths:** Git Bash rewrites `/tmp/...` arguments, for `docker cp` among others. Set
  `MSYS_NO_PATHCONV=1`.
- **Background servers:** stopping the task can leave the server on its port. Find the
  process by port and stop it; it must be your own process.
