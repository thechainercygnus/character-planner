# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:

- Use **Report a vulnerability** on this repository's
  [Security tab](https://github.com/thechainercygnus/character-planner/security/advisories/new)
  (GitHub's private vulnerability reporting).

Include what you found, how to reproduce it, and what an attacker could do with it. Don't
include real tokens, secrets or personal data. If you need to show one, use a made-up
value.

This is a hobby project with one maintainer, so responses are best effort. I aim to
acknowledge a report within a week and to fix confirmed problems in the next release.

## Supported versions

The latest release, and `main`. Fixes aren't backported to older versions. If you
self-host, upgrade to the latest release.

## In scope

The code in this repository: the API and worker (`src/`), the web app (`frontend/`), the
Docker image and compose files, and the CI workflows. Examples:

- Tokens, the Battle.net client secret, or Discord webhook URLs leaking into logs,
  responses or the browser.
- One user reading or changing another user's data, once multi-user support exists.
- Injection, request forgery, or bypassing the login flow.
- Weaknesses in the workflows, such as untrusted input reaching a `run:` step.

## Out of scope

- Blizzard's Battle.net API and Forever Companion's API. Report those to their owners.
- A self-hosted copy's own setup, for example an instance exposed to the internet without
  HTTPS, or a leaked `.env`. The [deploy guide](docs/deploy.md) covers safe settings.
- Rate limiting or denial of service against a single-user self-hosted instance.
