---
name: stack-debug
description: Look into Bryce's running Character Planner stack (Docker Compose, the homelab or a local test) to find why something failed. Covers service status, app and worker logs, the database, readiness, and a one-off probe inside the app container. Read-only unless Bryce says otherwise. Use when he reports an error from a deployed build ("I got an error adding X", "sync failed", "it won't start").
---

# Debug the running stack

This is Bryce's stack, holding his data: look, don't touch.
- **Ask before** restarting, recreating or stopping a service, writing to the database,
  or deleting anything.
- **Running branch code** against his database is out: use a copy.
- **Never print** a token, the client secret, `METRICS_TOKEN`, `POSTGRES_PASSWORD` or a
  webhook URL. Not from `.env`, not from the database, not from a container's
  environment.
- **On Windows Git Bash**, set `MSYS_NO_PATHCONV=1` for `docker exec` and `docker cp`,
  or `/tmp/...` paths get rewritten.

## 1. What's running
```bash
docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" | grep -i planner
```
- **Containers:** `character-planner-<service>-1`, for `app`, `worker`, `postgres`, `valkey`
  and `tailscale` (the one-time `migrate` has exited). The image tag says which build is
  running.
- **A service stuck "Restarting":** read its logs first. The app shares the Tailscale
  container's network, so a failing `tailscale` (an expired `TS_AUTHKEY`) keeps the app
  from starting.

## 2. Logs, around the moment it failed
```bash
docker logs character-planner-app-1 2>&1 | grep -v "/api/healthz" | grep -iE "error|warn|exception|<name or route>" | tail -40
docker logs character-planner-worker-1 2>&1 | grep -v "/api/healthz" | sed -n '/<HH:MM:SS>/,$p' | head -60
```
- **Access lines** carry a request id in brackets. Grep for it to follow one request.
- **With `REDIS_URL`, syncs and refreshes run in the worker.** A route that answered 202
  failed in the worker's log, not the app's: "Sync <slug>: ... failed: profile (404)".
- **A 404 from Battle.net for every endpoint** means it doesn't share that character. The
  name and region may be fine: check the level first, since characters below level 10
  return 404.

## 3. The database
Postgres (`compose.postgres.yaml`):
```bash
docker exec character-planner-postgres-1 psql -U planner -d planner -At -c "select id, name, surname, region, user_id from character;"
docker exec character-planner-app-1 character-planner-db current   # the schema version
```
- **Tables** are named after the models in `db.py`, lowercased (`snapshot`,
  `notificationdestination`, `"user"`, quoted).
- **Columns to leave out:** `usertoken`, `storedtoken`, `usersession.token_hash` and
  `notificationdestination.url` are secrets. Select only the other columns.
- **On SQLite:** query a copy of the file, never the live one.

## 4. Readiness and metrics
```bash
docker exec character-planner-app-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/api/readyz').read().decode())"
```
- **Readiness** reports the database at the newest migration, and the queue.
- **Metrics:** `/api/metrics` needs `METRICS_TOKEN`. Ask Bryce to paste the output rather
  than reading the token yourself.

## 5. A probe inside the app container
Use one when the answer needs the app's own code: an upstream answer, or what a parser
makes of it.
1. Write the probe with the Write tool, into the scratchpad. Use the app's modules:
   `get_settings()`, `make_engine`, `BlizzardClient`, `users.user_token` and
   `fields.get`.
2. Print only what answers the question: an entry's name, level and href, a status. Never
   a token, a header or a whole response with personal data.
3. Copy it in, run it, and remove it as root, since `docker cp` files belong to root:
   ```bash
   export MSYS_NO_PATHCONV=1
   docker cp "$(cygpath -w <scratchpad>/probe.py)" character-planner-app-1:/tmp/probe.py
   docker exec character-planner-app-1 python /tmp/probe.py
   docker exec -u 0 character-planner-app-1 rm -f /tmp/probe.py
   ```
4. Delete the scratchpad copy too.

Example: the "level 6 alt" diagnosis. The probe read the account listing with the user's
stored token and printed the alt's level and href, then the profile endpoint's status
(404) for that href's slug.

## 6. Report
Tell Bryce:
- what failed;
- the evidence (log lines, statuses), with nothing secret;
- whether it's a bug or upstream behaviour;
- the fix you propose, and anything you'd need him to run or allow.

Fixes go through `ship-pr`, with a test that reproduces the failure.
