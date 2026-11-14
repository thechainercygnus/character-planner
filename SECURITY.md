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

## What happens to a report

1. **Acknowledge.** I reply on the private advisory within a week, to say I've seen it.
2. **Assess.** I reproduce it and agree the impact with you, in the advisory. If it isn't
   a vulnerability, or it's out of scope (below), I say why and close it.
3. **Fix.** The fix is prepared privately, in the advisory's temporary fork where
   possible, with a test that fails without it.
4. **Release.** The fix ships in a new release. Its pull request carries the `security`
   label, so the release notes list it under **Security** ([Releasing](docs/releasing.md)).
5. **Publish.** The advisory is published with the affected and fixed versions, and a
   CVE when GitHub assigns one.
6. **Credit.** You're credited in the advisory and the release notes, by the name or
   handle you choose, unless you ask not to be.

Please keep the details private until the advisory is published. If a fix will take
longer than the next release, I'll tell you in the advisory and agree a date with you.

## Supported versions

The latest release, and `main`. Fixes aren't backported to older versions. If you
self-host, upgrade to the latest release.

## How the planner is secured

The [assurance case](docs/assurance-case.md) describes the threats at each trust
boundary, how the design counters them, and the gaps that remain. The
[architecture](docs/architecture.md) page shows how the parts fit together.

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
  HTTPS, or a leaked `.env`. The [self-hosting guide](docs/self-hosting.md) covers safe settings.
- Rate limiting or denial of service against a single-user self-hosted instance.
