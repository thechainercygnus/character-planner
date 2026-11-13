# 0019: Logging

Status: accepted (2026-11-12).

## Context

Only the worker set up logging. The API set up none, so its own messages were dropped, and
the refreshes logged nothing. When the item pool "wouldn't refresh" on an empty database,
nothing showed why. It was working: no level meant the whole pool, 1,669 items at about
0.75 s each, around 21 minutes, with no sign of it in the UI.

## Decision

- **One setup** (`logs.configure_logging`) for the API (from `create_app` on a real run;
  tests configure nothing) and the worker. Settings: `LOG_LEVEL` (default `INFO`),
  `LOG_FORMAT` (`text` or `json`) and `LOG_DIR`.
- **Where:** always the console. With `LOG_DIR`, rotating files (5 MB, 5 kept):
  - the API writes `server.log` and `access.log`;
  - the worker writes `worker.log`.

  One file per process, because two processes can't safely rotate the same file. Compose
  sets `LOG_DIR=/data/logs`.
- **Access log:** our middleware writes one line per request: client, method, path with
  query, status, duration and request id. Health checks go at `DEBUG`. uvicorn's own
  access log is off; its other messages go through the same handlers.
- **Request ids:** each request gets an id, or keeps a proxy's `X-Request-ID` when it looks
  like one. It's returned in `X-Request-ID` and on every line the request causes,
  including in worker threads.
- **Unhandled errors:** logged once with the traceback, and answered with a 500 that
  carries the request id, instead of a bare traceback from uvicorn.
- **Jobs:** each upstream batch (dungeons, items, item search, icons, enchant recipes)
  logs its start, progress every 50 items, a summary with the duration, and up to 20
  errors. Sync and pool refresh log their own start and summary.
- **Upstream requests:** httpx's request lines, at `DEBUG` only.
- **Redaction:** the formatters redact their whole output, tracebacks included:
  - bearer tokens;
  - `access_token`, `code`, `state`, `client_secret` and `password` in queries, forms and
    JSON;
  - URL passwords;
  - the configured client secret wherever it appears.

  A test logs in, syncs and checks that no token, code, state or secret reaches the files.

## Consequences

- A slow refresh now says what it's doing. The UI still doesn't show it; #17's job status
  will.
- `LOG_FORMAT=json` is ready for a log collector (#17).
