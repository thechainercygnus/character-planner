# Assurance case

Why the planner's security requirements are met, where they're met, and what isn't
covered. It's a threat model for one self-hosted instance serving one player; the
[architecture](architecture.md) page describes the parts. Tests that back a claim are
named, and `tests/test_security.py` holds the ones written for this page.

## What's protected

| Asset | Where it lives | Why it matters |
| --- | --- | --- |
| Battle.net client secret | `.env`, read into a `SecretStr` | Anyone holding it can call Blizzard as this app |
| Battle.net tokens (app token; optional login token; each user's with users on) | The database (`StoredToken`, `UserToken`) | API access as the app, or as the player |
| Sessions, with users on | A cookie; the database keeps only its SHA-256 (`UserSession`) | Acting as that user until it expires or they sign out |
| Discord webhook URLs | The database (`NotificationDestination`) | Anyone holding one can post to the channel |
| The character's data and the player's plans | The database | Personal data; edits the player made |
| The released image | GHCR | What self-hosters run |

## Security requirements

1. Secrets and tokens never reach logs, API responses or the browser.
2. Only the person who runs the instance can read or change its data.
3. Input from the browser and from upstream APIs can't corrupt data or run code.
4. Calls to upstream services are authentic and confidential.
5. The image and its dependencies come from this repository's reviewed code and are
   checked for known vulnerabilities.

## Trust boundaries

```
[browser] ──(1)── [API] ──(3)── [Battle.net]     (4) [worker] ── [database] ── [API]
                    │   ──(3)── [Forever Companion]
  (2) Tailscale, your proxy,  ──(3)── [Discord]
      or localhost in front
```

### 1. Browser ↔ API

- **Threat: someone else reaches the API.** By default the API has **no login of its
  own**: anyone who reaches it can read and edit everything (requirement 2). Access
  control is the network in front of it (boundary 2), and the defaults are built around
  that:
  - Compose binds to `127.0.0.1` unless `PLANNER_BIND` says otherwise
    (`compose.yaml`).
  - The Tailscale option serves it only on the owner's tailnet, over HTTPS.
  - The [self-hosting guide](self-hosting.md) says a reverse proxy must ask for a
    password, with an example.
- **With `PLANNER_USERS=on` (#16, ADR 0037),** the API needs a Battle.net sign-in:
  - Every `/api` request needs one, except health, about, who's signed in and guest
    mode.
  - Sessions are random tokens in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over
    HTTPS), stored only as SHA-256 and revoked at logout.
  - Each request resolves its character through the signed-in user, so another user's
    character answers 404 (`tests/test_users.py`).
  - Instance-wide settings are the admin's.
- **Threat: cross-site request forgery (CWE-352).**
  - The API sends no CORS headers, so other sites' scripts can't read responses or make
    preflighted requests: anything with a JSON body, `PUT` or `DELETE`
    (`test_no_cross_origin_access_is_granted`).
  - A cross-site HTML form can only send form encodings or `text/plain`, and FastAPI
    parses a JSON body only when the content type is JSON, so a forged body is refused
    with 422 (`test_a_form_cant_send_a_json_body`).
  - Every state-changing API request (`POST`, `PUT`, `PATCH`, `DELETE`) must carry the
    `X-Requested-With: character-planner` header the web app sends. A form can't set a
    header, so even the `POST`s with no body (sync, the refreshes, a test alert) are
    refused cross-site with 403 (#124, `test_state_changing_requests_need_the_app_header`).
- **Threat: DNS rebinding.** A page that rebinds its own name to `127.0.0.1` would
  reach a local-only instance from the player's browser. The API answers only to
  `localhost`, `127.0.0.1`, `[::1]`, `*.ts.net` behind the Tailscale overlay, and the
  names listed in `PLANNER_HOSTS`. Any other `Host` gets 400 before a route runs, reads
  included (#124, `test_an_unknown_host_is_refused`). Nobody outside Tailscale can point
  a `ts.net` name at an address, so the wildcard can't be used for rebinding.
- **Threat: script injection (XSS, CWE-79).** The web app is React, which escapes all
  text. It doesn't use `dangerouslySetInnerHTML` or `innerHTML`, and links opened in a
  new tab carry `rel="noreferrer"` (CWE-1022).
- **Threat: malformed input (CWE-20).** Every route's path, query and body are typed
  Pydantic models with ranges and patterns: levels 1 to 60, ids above 0, quest ids
  matching `[a-z0-9-]`, effect names from a fixed list, and webhook URLs that must
  match Discord's form (`test_input_is_validated_before_it_is_stored`).
- **Threat: secrets in responses (CWE-200).** No route returns a token or the client
  secret. Webhook URLs come back masked (`test_urls_are_masked_and_redacted`).

### 2. The network in front

- The default is localhost only. With `PLANNER_BIND=0.0.0.0` the app is plain HTTP on
  the LAN, which the self-hosting guide presents as a home-network option.
- TLS, and with a proxy, the password, are the front end's job: Tailscale's certificates
  or the proxy's.

### 3. API and worker ↔ upstream services

- **Authenticity and confidentiality (requirement 4).** Every call uses HTTPS through
  `httpx` with certificate verification on. The code never turns it off.
- **Credentials.**
  - The client secret is a `SecretStr`, sent only to Battle.net's token endpoint.
  - Syncs use the app's own Client Credentials token, renewed before it expires
    (ADR 0027). The optional login uses OAuth's `state`: random, single-use and
    expiring after 10 minutes, so a callback the app didn't start is refused
    (`test_a_login_callback_needs_a_state_this_app_issued`).
- **Untrusted responses.** Upstream JSON is undocumented and treated as untrusted:
  - It's stored raw, then read through defensive accessors that turn a missing or
    reshaped field into "unknown" rather than an error (`fields.py`, ADR 0002).
  - Nothing from a response is executed, used as a file path or put into SQL: class
    and race names are looked up in a fixed map, never turned into paths (`classes.py`).
- **Availability.** Batches are paced and stop at the first `429`. Failures are stored
  and reported, never retried in a tight loop (ADR 0024).

### 4. Worker and API ↔ database

- **Injection (CWE-89).** All queries go through SQLModel and SQLAlchemy with bound
  parameters. The code has no raw SQL.
- **Integrity.** Migrations run on every start (ADR 0022), writes are short transactions
  (ADR 0018), and leases keep two refreshes from running at once (ADR 0024).
- **Gap:** tokens and webhook URLs are stored unencrypted in the SQLite file. Anyone
  who can read the Docker volume can read them, so the host and its backups are part of
  the trusted base.

## Secrets in logs (requirement 1)

- **Logging:** every log line, messages and tracebacks alike, passes through redaction
  before it's written. Known secret values (the client secret) and patterns (bearer
  tokens, OAuth codes, `access_token=`, webhook tokens) become `[redacted]` (ADR 0019).
- **Static check:** a custom Semgrep taint rule (`.semgrep/rules/no-secrets-in-logs.yaml`,
  #57) follows the client secret (`get_secret_value()`) and tokens (`access_token`) and
  fails CI if one reaches a log call, `print` or a raised exception's message without
  passing through `redact`. Its results go to code scanning, and it has its own test
  cases.
- **Tests:** `test_secrets_are_redacted`, `test_known_secret_values_are_redacted_anywhere`,
  `test_formatters_redact_messages_and_tracebacks`,
  `test_no_token_code_or_secret_reaches_the_log_files`,
  `test_webhook_urls_never_reach_the_log` and `test_tokens_are_never_logged`.
- **Repository:** the rules forbid committing `.env`, samples or databases, and
  gitleaks scans every push and pull request.

## The supply chain (requirement 5)

- **Dependencies** are locked (`uv.lock`, `package-lock.json`), updated by Dependabot,
  and checked on every pull request by Dependency Review, which fails on known
  vulnerabilities or a license outside the allowed list.
- **Code** is analysed by CodeQL (Python, TypeScript, Actions). pyright runs in strict
  mode across `src/`, and the tests fail on any warning.
- **Workflows:**
  - every action is pinned to a commit SHA;
  - each job has the least permissions it needs;
  - no workflow runs untrusted pull request code with secrets (no `pull_request_target`);
  - OpenSSF Scorecard reports on these practices.
- **The image:**
  - its base images are pinned by digest;
  - it runs as an unprivileged user (uid 10001);
  - Trivy scans it and the Dockerfile.
  - A release stops on a fixable high or critical vulnerability. Released images carry
    build provenance, a keyless cosign signature and an SBOM ([Releasing](releasing.md),
    ADR 0026).

## Common weaknesses, and where they're countered

| Weakness | Countered by |
| --- | --- |
| CWE-79 Cross-site scripting | React escaping; no raw HTML |
| CWE-89 SQL injection | SQLModel bound parameters; no raw SQL |
| CWE-20 Improper input validation | Pydantic models on every route |
| CWE-352 Cross-site request forgery | No CORS; the app's header on every state-changing request; JSON bodies need a JSON content type; OAuth `state` |
| CWE-346 Origin validation error (DNS rebinding) | `Host` allow-list |
| CWE-200, CWE-532 Exposure of secrets, in logs | Redaction on every log line; the Semgrep rule in CI; masked webhook URLs; `SecretStr` |
| CWE-295 Improper certificate validation | `httpx` defaults; never disabled |
| CWE-306 Missing authentication | The network boundary (localhost, Tailscale, a proxy with a password); with `PLANNER_USERS=on`, a Battle.net sign-in on every `/api` request (ADR 0037) |
| CWE-250 Execution with unnecessary privileges | Non-root image user |
| CWE-1104 Unmaintained third-party components | Dependabot, Dependency Review, Trivy |
| CWE-1022 Untrusted link targets | `rel="noreferrer"` on new-tab links |

## Out of scope

As in [SECURITY.md](https://github.com/thechainercygnus/character-planner/blob/main/SECURITY.md):
- Blizzard's and Forever Companion's own services.
- A self-hosted copy's own setup: an instance exposed without HTTPS or a password, or a
  leaked `.env`.
- Denial of service against a single-user instance.

Multi-user isolation becomes a requirement with #16, and this page grows with it.
