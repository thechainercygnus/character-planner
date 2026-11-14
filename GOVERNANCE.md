# Governance

How decisions are made in Character Planner, who can do what, and how that changes as
the project grows.

## The model: one maintainer

Character Planner has a single maintainer, Bryce Jenkins
([@thechainercygnus](https://github.com/thechainercygnus)), who has the final say on
what goes in, what's planned and when a release ships. It's a hobby project, so
decisions are made in the open but not by vote.

## How decisions are made and recorded

- **Issues** are where work is proposed and discussed. Anyone can open one, as
  [CONTRIBUTING.md](CONTRIBUTING.md) describes.
- **The roadmap**, [issue #25](https://github.com/thechainercygnus/character-planner/issues/25),
  is the work order. Milestones group its issues into releases.
- **Architecture decision records** in [`docs/adr/`](docs/adr/) record every decision
  with lasting consequences: what was decided, why, and what follows from it. A later
  decision supersedes an earlier one with a new record, never by editing the old one.
- **Pull requests** carry every change to `main`. The maintainer merges them; nobody
  pushes to `main` directly.
- **Releases** are tagged by the maintainer ([Releasing](docs/releasing.md)).

## Roles

| Role | Who | Can |
| --- | --- | --- |
| Maintainer | Bryce Jenkins | Merge pull requests, tag releases, manage the repository's settings, secrets and the published image, triage issues, and handle security reports ([SECURITY.md](SECURITY.md)) |
| Contributor | Anyone | Open issues and pull requests, review, and discuss. Commits are signed off under the [DCO](CONTRIBUTING.md#sign-off-your-commits-dco) |
| AI coding agent | Claude Code sessions the maintainer runs | Work an issue on a branch and open a pull request, following [CLAUDE.md](CLAUDE.md). It can't merge, tag a release or change settings: commits, pushes and merges need the maintainer's go-ahead |
| Bots | Dependabot; the GitHub Actions workflows | Dependabot opens pull requests for dependency updates. Workflows run checks and publish releases, each with the least permissions it needs |

### What protects `main`

A ruleset on `main` applies to everyone, the maintainer included, with no bypass:

- changes land only through a pull request;
- the branch can't be deleted or force-pushed;
- these checks must pass: `check`, `frontend`, `docker`, `secret-scan`, and CodeQL's
  `analyze` for Python, TypeScript and Actions.

## Access continuity

The project should be able to go on if the maintainer can't: someone else able to merge,
release, and manage the repository, its secrets and the published image. **This isn't
arranged yet.** The options (moving the repository to the durishlabs organisation with
a second owner, or naming a trusted person with documented access) are open on
[issue #83](https://github.com/thechainercygnus/character-planner/issues/83). This
section and an architecture decision record will say what was chosen.

Until then, the code, its history, the documentation and every release stay public
under the [AGPL-3.0-or-later](LICENSE), so anyone can fork and continue the project.

## Code of conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md). The maintainer
enforces it.

## Changing this document

Changes to governance go through a pull request like any other, with the reasons in its
description. A second maintainer joining is such a change: it updates the roles and how
decisions are made, and it's recorded as an architecture decision record.
