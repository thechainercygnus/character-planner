# 0011: One image, an API and a worker, served over Tailscale

Status: accepted (2026-11-12)

## Context

Issue #1: run the planner on the homelab with scheduled syncs and pool refreshes, and
reach it remotely. It should grow into a shared service later (#17: Postgres, a job
runner). Battle.net's `wow.profile` scope needs the authorization code flow, which gives a
24-hour token and no refresh token. Battle.net only accepts the redirect URIs registered
on the client, and needs HTTPS for anything but localhost.

## Decision

- One Docker image: the frontend is built in a Node stage, and the Python stage serves it
  from FastAPI. It runs as a non-root user and checks `/api/healthz`.
- Two compose services from that image: `app` (uvicorn) and `worker`
  (`character-planner-worker`). Sync and pool refresh live in `jobs.py`, called by the
  API routes and the worker alike. A separate worker is the shape #17 needs.
- The worker runs each job when its interval has passed (sync 6h, pool 24h, from
  settings). A failure waits for the next interval. A sync without a valid login is
  skipped and logged; the pool refresh waits until a sync has stored the level.
- SQLite stays, on a volume, with WAL mode and a 10 second busy timeout so the two
  processes can share it.
- Remote access goes through a Tailscale sidecar (`compose.tailscale.yaml`) using
  `tailscale serve`: HTTPS on the tailnet with Tailscale's certificate, no host ports,
  no Funnel. That replaces the Caddy proxy in the original issue.
- Secrets come from `.env` on the server via `env_file`; the image build ignores it.
- CI builds the image and smoke-tests the API, the frontend and `worker --once`.

## Consequences

- Scheduled syncs stop 24 hours after each login until someone logs in again. The
  worker's log says so.
- Each tailnet hostname is a separate Battle.net redirect URI to register.
- Only one machine runs the worker: SQLite and a single schedule don't coordinate across
  hosts. #17 replaces both.
- A Caddy-fronted LAN setup is still possible with `PLANNER_BIND`, but isn't provided.
