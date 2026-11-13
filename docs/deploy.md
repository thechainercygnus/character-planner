# Deploying to the homelab

One Docker image runs two containers from `compose.yaml` (ADR 0011):

- **app**: the API, serving the built frontend, with a health check on `/api/healthz`.
- **worker**: syncs the character every 6 hours and refreshes the item pool every 24.

They share a SQLite database on the `planner-data` volume. `compose.tailscale.yaml` adds
a Tailscale sidecar that serves the app over HTTPS on your tailnet.

## What the server needs

- Docker with the compose plugin, v2.24 or newer (`docker compose version`).
- This repository checked out.
- For Tailscale: HTTPS certificates and MagicDNS turned on for the tailnet
  (admin console > DNS), and an auth key (admin console > Settings > Keys).

## 1. Configure

```bash
cp .env.example .env
```

Fill in `BNET_CLIENT_ID`, `BNET_CLIENT_SECRET` and the character name. Then set the
redirect URI for where you'll open the app:

| Access | `BNET_REDIRECT_URI` |
|---|---|
| Tailscale | `https://character-planner.<tailnet>.ts.net/auth/callback` |
| On the server itself | `http://localhost:8000/auth/callback` |

Add the same URI to the client's redirect URIs in the
[Battle.net developer portal](https://develop.battle.net/access/clients). It must match
exactly. Your tailnet name is under DNS in the Tailscale admin console.

For Tailscale, also set `TS_AUTHKEY` (and `TS_HOSTNAME` to use a name other than
`character-planner`).

## 2. Start

Tailscale:

```bash
docker compose -f compose.yaml -f compose.tailscale.yaml up -d --build
```

Local only (port 8000 on the server's loopback; `PLANNER_BIND=0.0.0.0` opens it to the LAN):

```bash
docker compose up -d --build
```

Check it:

```bash
docker compose ps
docker compose logs -f worker
```

Once the Tailscale container has joined, remove `TS_AUTHKEY` from `.env`. Its state is
kept on the `tailscale-state` volume.

### Alerts

Open **Alerts** in the status bar and paste a Discord webhook URL (channel settings →
Integrations → Webhooks). **Send a test** checks it. The worker sends queued alerts on
every pass (`WORKER_POLL_SECONDS`, default 60) and warns 2 hours before the 24-hour
Battle.net login expires, so keep it running. Alerts from a sync you start yourself are
sent straight away. See ADR 0021.

### Logs

Both containers log to the console (`docker compose logs -f app worker`) and to rotating
files in `/data/logs` on the data volume (ADR 0019):

- `server.log`: the API, including each refresh's start, progress every 50 items and summary.
- `access.log`: one line per request, with its id, status and duration. Health checks are left out.
- `worker.log`: the worker's scheduled jobs.

Read them from the host with:

```bash
docker compose exec app tail -f /data/logs/server.log
```

Each file rotates at 5 MB and keeps 5 old copies. `LOG_LEVEL=DEBUG` in `.env` adds every
upstream request; `LOG_FORMAT=json` writes one JSON object per line for a log collector.
Tokens, the client secret and OAuth codes are always replaced by `[redacted]`.

## 3. Log in and sync

Open the app, choose **Log in**, then **Sync now**. The worker picks up from there. On a
new instance, the first sync also loads the item pool and enchant data in the background
(a few minutes; the status bar says so), so there's nothing else to click (ADR 0024).

Battle.net gives no refresh token, so each login lasts 24 hours. While it's valid the
worker syncs every `SYNC_EVERY_HOURS`; after that its log says
`sync: skipped: no valid login` until you log in again. The pool refresh starts after the
first sync, once your level is known.

## Moving existing data in

To bring the database from a development machine, stop the stack and copy the file into
the volume (as root, then hand it to the app's user, uid 10001):

```bash
docker compose down
docker run --rm -v character-planner_planner-data:/data -v "$PWD/data:/src:ro" alpine \
  sh -c 'cp /src/character-planner.db /data/ && chown 10001:10001 /data/character-planner.db'
docker compose up -d
```

Copy it while the development app is stopped, so its WAL file has been folded in.

## Update

```bash
git pull
docker compose -f compose.yaml -f compose.tailscale.yaml up -d --build
```

The `migrate` service runs first and brings the database's schema up to date, keeping its
data (ADR 0022); the API and the worker start once it has finished. If it fails,
`docker compose logs migrate` says why, and nothing else starts. Back up the data volume
before an upgrade (below).

## Back up

The database is one file on the volume:

```bash
docker run --rm -v character-planner_planner-data:/data -v "$PWD:/backup" alpine \
  cp /data/character-planner.db /backup/character-planner-$(date +%F).db
```

Back up while the stack is stopped, or accept that the last few seconds of writes may be
missing.
