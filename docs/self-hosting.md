# Self-hosting

This guide takes you from nothing to your own planner syncing your WoW Forever character.
It assumes Docker and nothing else. About 20 minutes, most of it waiting for the first item
data to load.

The planner is one Docker image run as three Compose services (ADR 0011, ADR 0022):

- **migrate** brings the database schema up to date, then exits;
- **app** is the web page and the API;
- **worker** syncs your character every 6 hours and refreshes item data.

Everything is kept in one SQLite database on a Docker volume.

## Before you start: keep it private

The planner is built for one person and **has no sign-in of its own**. Anyone who can open
the page can:

- edit your plans;
- set where alerts go;
- start data refreshes that use your Battle.net client.

So reach it only from places you trust:

- this machine;
- your home network;
- a private network such as Tailscale;
- behind a reverse proxy that asks for a password.

Don't publish it on the open internet as it is.

## 1. What you need

- **Docker with Compose v2.24 or newer.** Check with `docker compose version`. Docker
  Desktop on Windows or macOS works, as does Docker Engine on Linux. The image runs on amd64
  and arm64, a Raspberry Pi 4 or 5 included.
- **Git**, to fetch the Compose files.
- **A Battle.net account** with a WoW Forever character.

## 2. Build the compose file(s)

Pin at the release you want (see [Releases](https://github.com/thechainercygnus/character-planner/releases)).
Here is a sample compose file to get you started:

```yaml
name: character-planner

x-planner: &planner
  build: .
  image: ${PLANNER_IMAGE:-ghcr.io/thechainercygnus/character-planner:latest}
  env_file: .env  # Battle.net client and redirect URI; never committed
  environment:
    DATABASE_URL: sqlite:////data/character-planner.db
    POST_LOGIN_REDIRECT: /
    # Log files on the data volume, beside the console output (ADR 0019).
    LOG_DIR: /data/logs
  volumes:
    - planner-data:/data
  restart: unless-stopped

services:
  # Runs the schema migrations once, before the API and the worker start (ADR 0022).
  migrate:
    <<: *planner
    command: ["character-planner-db", "upgrade"]
    restart: "no"
    healthcheck:
      disable: true

  app:
    <<: *planner
    depends_on:
      migrate:
        condition: service_completed_successfully
    # Local-only by default. PLANNER_BIND=0.0.0.0 exposes it to the LAN.
    ports:
      - "${PLANNER_BIND:-127.0.0.1}:${PLANNER_PORT:-8000}:8000"

  worker:
    <<: *planner
    command: ["character-planner-worker"]
    healthcheck:
      disable: true  # the image's check is the API's
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  planner-data:
```

If you want to serve the app over Tailscale create `compose.tailscale.yaml`:

```yaml
# Serve the app over HTTPS on your tailnet, as https://<TS_HOSTNAME>.<tailnet>.ts.net
# Tailscale provides the certificate; nothing is published on the host's ports.
#
#   docker compose -f compose.yaml -f compose.tailscale.yaml up -d --build
#
# Needs TS_AUTHKEY in .env for the first start (see docs/self-hosting.md).

services:
  tailscale:
    image: tailscale/tailscale:stable
    hostname: ${TS_HOSTNAME:-character-planner}
    environment:
      TS_AUTHKEY: ${TS_AUTHKEY:-}
      TS_STATE_DIR: /var/lib/tailscale
      TS_SERVE_CONFIG: /config/serve.json
    volumes:
      - tailscale-state:/var/lib/tailscale
      - ./deploy/tailscale:/config:ro
    restart: unless-stopped

  app:
    # Share the sidecar's network: Tailscale serve proxies to 127.0.0.1:8000.
    network_mode: service:tailscale
    ports: !reset []
    depends_on:
      - tailscale

volumes:
  tailscale-state:
```

You will also need to create the `serve.json` configuration in `./deploy/tailscale`:

```json
{
  "TCP": {
    "443": {
      "HTTPS": true
    }
  },
  "Web": {
    "${TS_CERT_DOMAIN}:443": {
      "Handlers": {
        "/": {
          "Proxy": "http://127.0.0.1:8000"
        }
      }
    }
  },
  "AllowFunnel": {
    "${TS_CERT_DOMAIN}:443": false
  }
}
```

Alternatively add a container for your reverse proxy of choice or add the required configuration to your existing one.

## 3. Choose how you'll reach it

| How | Open it at | In `.env` |
| --- | --- | --- |
| This machine only (default) | `http://localhost:8000` | nothing else |
| Your home network | `http://<the server's address>:8000` | `PLANNER_BIND=0.0.0.0` and `PLANNER_HOSTS=<the server's address>` |
| Tailscale (HTTPS on your tailnet) | `https://character-planner.<tailnet>.ts.net` | `TS_AUTHKEY`, optionally `TS_HOSTNAME` |
| Your own reverse proxy with HTTPS, on the same machine | `https://planner.example.com` | `PLANNER_HOSTS=planner.example.com`; the proxy forwards to `127.0.0.1:8000` |

**Portainer:** `deploy/portainer.yaml` is the Tailscale setup as one self-contained stack:
- **To use it:** paste it into **Stacks → Add stack → Web editor**, and set its variables
  under **Environment variables**. The list is at the top of the file.
- **Self-contained:** it needs no `.env`, no build and no files from the repository.
- **Releases:** it runs the release pinned in it. Set `PLANNER_IMAGE` to run another.
- **One name per host:** use a different stack name if a `character-planner` Compose
  project already runs on the same host.

The planner only answers to the names it's opened at: `localhost`, `127.0.0.1`, your
tailnet name, and what you list in `PLANNER_HOSTS` (comma separated, for example
`PLANNER_HOSTS=192.168.1.20,planner.local`). Any other name gets "Invalid host header".
That stops a malicious web page from reaching your planner through your own browser (DNS
rebinding). If you see that message, add the name in your address bar to `PLANNER_HOSTS`
and restart.

To change the port, set `PLANNER_PORT`. You don't sign in to Battle.net through the
planner, so the address doesn't go into your Battle.net client.

**Tailscale** needs HTTPS certificates and MagicDNS turned on for your tailnet (admin
console, DNS), and an auth key (admin console, Settings, Keys). Your tailnet's name is
under DNS.

**A reverse proxy** must ask for a password, because the planner doesn't. With Caddy, for
example (make the hash with `caddy hash-password`):

```
planner.example.com {
    basic_auth {
        you <password hash>
    }
    reverse_proxy 127.0.0.1:8000
}
```

## 4. Create a Battle.net client

Each planner uses its owner's own Battle.net API client. With it, the planner reads your
character's public data (the same as the Armory) and keeps syncing on its own. There's no
Battle.net login to renew (ADR 0027).

1. Sign in at the [Battle.net developer portal](https://develop.battle.net/access/clients)
   and create a client. The name is up to you. If the form asks for a redirect URL, enter
   `http://localhost:8000/auth/callback`: the planner doesn't use it yet.
2. Copy the **client ID** and **client secret** into `.env`:

   ```
   BNET_CLIENT_ID=...
   BNET_CLIENT_SECRET=...
   ```

Keep `.env` private: the secret is like a password. The planner never logs it.

## 5. Fill in `.env`

Besides the client:

- `BNET_REGION`: your account's region, `us`, `eu`, `kr` or `tw`.
- `CHARACTER_NAME` and `CHARACTER_SURNAME`: your character's first name and surname, as
  shown in game. Forever looks characters up by both. They name the **first** character
  only: on its first start the planner saves that character, with `BNET_REGION`, in its
  database, and reads these settings no more (ADR 0036). Add more characters in the app,
  from the character menu at the top left: **Add a character…**. After you **Sign in with
  Battle.net**, the form lists your account's characters to pick from. Without signing in,
  you type a character's name, surname and region instead. The worker syncs them all.
- `PLANNER_IMAGE`: the release to run, for example
  `PLANNER_IMAGE=ghcr.io/thechainercygnus/character-planner:0.1`. `0.1` follows the
  latest `0.1.x`; `0.1.0` stays put.
- For Tailscale: `TS_AUTHKEY`, and `TS_HOSTNAME` for a name other than `character-planner`.
- `OPERATOR_CONTACT`: how to reach you, shown on the privacy notice. See
  [Privacy](privacy.md), which also covers deleting the character's data.

Leave `BNET_REDIRECT_URI`, `POST_LOGIN_REDIRECT` and `DATABASE_URL` as they are.

## 6. Start it

```bash
docker compose pull
docker compose up -d
```

With Tailscale, add both files to every command:

```bash
docker compose -f compose.yaml -f compose.tailscale.yaml pull
docker compose -f compose.yaml -f compose.tailscale.yaml up -d
```

Don't add `--build`: that builds from the source instead of running the published image.

Check that it's up:

```bash
docker compose ps
```

`migrate` should have exited with code 0, and `app` should be `healthy` after half a minute.
With Tailscale, once the `tailscale` container has joined, remove `TS_AUTHKEY` from `.env`.
Its state stays on the `tailscale-state` volume.

## 7. Sync

Open the planner. **Try it without an account** works straight away: pick a class and a
level to see the best items and dungeons for it.

1. Choose **Sync now**. The planner reads your character's profile, gear, talents and
   professions. No login: it uses the client from step 4.
2. **The first sync also loads item, enchant and talent data in the background.** That
   takes a few minutes, and the status bar says so (ADR 0024). Upgrades and Dungeons fill
   in when it's done.

From then on, the worker syncs every 6 hours (`SYNC_EVERY_HOURS`) on its own, for as long
as it runs. The planner gets a new Battle.net token by itself when the old one runs out
(ADR 0027).

## 8. Other people (optional)

By default the planner has no sign-in: it's yours alone, kept private by the network
(see "Before you start"). To let guildmates use it, each seeing only their own
characters, turn users on (ADR 0037):

```
PLANNER_USERS=on
```

Then `docker compose up -d`. Every page now asks for a Battle.net sign-in, so register
`BNET_REDIRECT_URI` on your Battle.net client (step 4).

- **Sign in first.** The first account to sign in becomes the admin and takes over every
  character already tracked.
- **Sign-ups are closed after that.** To let others in, set `PLANNER_SIGNUPS=on`, then
  turn it off again once they've signed in.
- **Each user sees only their own characters.**
- **Only the admin** can see and change the alert webhooks, change enchant corrections,
  and start the bulk refreshes in the ⋯ menu.
- **Leaving:** each user can delete their own account on the Privacy page. To delete one
  for them, use `character-planner-db delete-user ACCOUNT_ID --yes` (see
  [Privacy](privacy.md)).

## 9. Alerts (optional)

The planner can post to a Discord channel:

- after a sync: level-ups, a gear target reached or now in reach, and new upgrades worth
  having;
- about the planner itself: a scheduled job that failed (a refused Battle.net client
  among them), or many errors from Battle.net or Forever Companion.

You choose which alerts each channel gets.

1. In Discord, open the channel's settings, then **Integrations**, **Webhooks**, and
   **New Webhook**. Copy its URL.
2. In the planner, open **Alerts** in the status bar, paste the URL, and choose **Send a
   test**.

The worker sends queued alerts every minute, so keep it running (ADR 0021).

## 10. Logs

Both containers log to the console and to rotating files on the data volume (ADR 0019):

```bash
docker compose logs -f app worker
docker compose exec app tail -f /data/logs/server.log
```

- `server.log`: the API, including each refresh's progress and summary.
- `access.log`: one line per request.
- `worker.log`: the scheduled jobs.

Each file rotates at 5 MB and keeps 5 old copies. `LOG_LEVEL=DEBUG` adds every upstream
request, and `LOG_FORMAT=json` writes JSON lines for a log collector. Tokens, the client
secret and login codes are always replaced by `[redacted]`.

## 11. Back up and upgrade

**What's kept, and for how long.** Blizzard's API terms limit everything fetched from
Battle.net to 30 days (ADR 0034):
- the planner deletes it after 30 days, every day and after each sync, and fetches what
  it still needs again before then;
- the Progress tab keeps older points with only their date, level and average item level;
- a character Battle.net no longer has is deleted at once.

Your own settings, plans and manual entries stay until you change them. A backup holds
whatever the database held that day, so treat it like the database.

**Back up** the database, one file on the volume:

```bash
docker run --rm -v character-planner_planner-data:/data -v "$PWD:/backup" alpine \
  cp /data/character-planner.db /backup/character-planner-$(date +%F).db
```

Do it while the planner is stopped (`docker compose stop`), or accept that the last few
seconds of writes may be missing.

On Postgres (below), dump it instead:

```bash
docker compose -f compose.yaml -f compose.postgres.yaml exec -T postgres   pg_dump -U planner planner > character-planner-$(date +%F).sql
```

**Upgrade:**

1. Read the release notes first: they list security fixes and anything you need to do.
2. Back up.
3. Fetch the new release's files:

   ```bash
   git fetch --tags && git checkout v0.1.1
   ```

4. Change `PLANNER_IMAGE` if you pinned a full version.
5. Run the commands from step 6 again.

`migrate` updates the database schema and keeps your data. If it fails,
`docker compose logs migrate` says why, and nothing else starts until it's fixed.

To check that an image really comes from this project before running it, see
[Verifying an image](releasing.md#verifying-an-image).

**Postgres (optional).** SQLite suits one person. For several people using it at once,
with users on (step 8), run it on Postgres (ADR 0038). Add a password to `.env`:

```
POSTGRES_PASSWORD=<a long random password>
```

Then start with the Postgres override, in place of the plain command from step 6:

```bash
docker compose -f compose.yaml -f compose.postgres.yaml up -d
```

Use both `-f` files for every `docker compose` command from then on.

**Background jobs (optional).** With several people syncing at once, run Syncs as
background jobs on a queue (ADR 0039). Then requests stay short, and the page follows
each Sync until it's done:

```bash
docker compose -f compose.yaml -f compose.redis.yaml up -d
```

It adds Valkey, the BSD-licensed, Redis-compatible server, and the worker container
works the queue. Combine it with `compose.postgres.yaml` for a shared instance.

With the queue, every process shares one request budget per upstream (ADR 0040).
- **Forever Companion:** 100 requests a minute, under its 120.
- **Battle.net:** 50 a second and 30,000 an hour, under Blizzard's limits.

So however many people sync at once, the planner stays within both.

The admin's refreshes in the ⋯ menu queue too, and the status bar shows them until
they're done. Each can be started by hand at most once per 10 minutes
(`REFRESH_COOLDOWN_MINUTES`; 0 turns it off). The worker's schedule isn't limited.

**How often a character can be synced by hand:** once per 15 minutes, counted from its
last sync, scheduled ones included. Change it with `SYNC_COOLDOWN_MINUTES` in `.env`; 0
turns it off.

**Moving to Postgres.** To keep an existing instance's history:
1. Back up, then stop the planner: `docker compose stop app worker`.
2. Start Postgres on its own:

   ```bash
   docker compose -f compose.yaml -f compose.postgres.yaml up -d postgres
   ```

3. Copy the SQLite database into it. `copy-to` reads the target from
   `COPY_TO_DATABASE_URL`, refuses one that already holds data, and brings both up to
   the newest schema first:

   ```bash
   docker compose run --rm      -e "COPY_TO_DATABASE_URL=postgresql+psycopg://planner:<password>@postgres:5432/planner"      migrate character-planner-db copy-to
   ```

4. Start everything with both files, as above. The SQLite file stays on the volume until
   you delete it.

## 12. Fair use

- **Battle.net:** the planner uses your own client, within Blizzard's limits for it.
- **Forever Companion:** item and dungeon data comes from
  [Forever Companion](https://forevercompanion.io), a free fan-run service that allows 120
  requests a minute per IP address. The planner paces itself to stay under that. Leave
  `COMPANION_REQUEST_PAUSE` at its default; it's set for that limit.
- **Refreshes:** the worker refreshes data on a schedule. The manual refreshes in the ⋯
  menu are for when something looks out of date, not for running in a loop.

## 13. Troubleshooting

| What you see | Why | What to do |
| --- | --- | --- |
| `Sync failed: Battle.net refused the client ID and secret (HTTP 401)` | A typo in `BNET_CLIENT_ID` or `BNET_CLIENT_SECRET`, or the client was deleted or its secret changed | Copy both again from the developer portal, then `docker compose up -d` |
| The status bar says `Battle.net can't find …`, and the logs say `character … not found` | Name, surname or region doesn't match the character | Fix `CHARACTER_NAME`, `CHARACTER_SURNAME` or `BNET_REGION` in `.env`. The mistyped character is already saved, so remove it with `docker compose exec app character-planner-db erase --yes` (it has no data to lose), then `docker compose up -d` and sync again |
| The status bar says `No Battle.net client`, and `worker.log` says `skipped: no Battle.net client` | `BNET_CLIENT_ID` or `BNET_CLIENT_SECRET` is empty, or Compose didn't read `.env` | Fill in `.env` beside `compose.yaml`, then `docker compose up -d` |
| The page says `Invalid host header` | The planner doesn't answer to the name in your address bar (#124) | Add that name to `PLANNER_HOSTS` in `.env` (comma separated), then `docker compose up -d` |
| Upgrades and Dungeons stay empty after the first sync | Item data is still loading | Wait for the status bar's note to clear. `server.log` shows progress every 50 items |
| `migrate` exited with an error, and the app doesn't start | The schema update failed | `docker compose logs migrate`. Restore your backup if needed, and [report it](https://github.com/thechainercygnus/character-planner/issues) |
| `pull access denied` for the image | A typo in `PLANNER_IMAGE`, or a version that doesn't exist | Copy the image name from the release notes |

For anything else, open an
[issue](https://github.com/thechainercygnus/character-planner/issues) with the relevant log
lines. Report security problems privately, as [SECURITY.md](https://github.com/thechainercygnus/character-planner/blob/main/SECURITY.md) explains.

## Running from source

To change the code, build the image from your checkout instead: leave `PLANNER_IMAGE`
unset and use `docker compose up -d --build`. [CONTRIBUTING.md](https://github.com/thechainercygnus/character-planner/blob/main/CONTRIBUTING.md) covers
development. If you
host a modified copy for others, set `SOURCE_URL` to your fork. The AGPL asks you to offer
your users the source, and the page footer links to it.

## Moving an existing database in

To bring a database from another machine, stop both planners (so the database's WAL file
has been folded in), then copy the file into the volume. It belongs to the planner's user,
uid 10001:

```bash
docker compose down
docker run --rm -v character-planner_planner-data:/data -v "$PWD/data:/src:ro" alpine \
  sh -c 'cp /src/character-planner.db /data/ && chown 10001:10001 /data/character-planner.db'
docker compose up -d
```

`migrate` brings an older database up to date on start.
