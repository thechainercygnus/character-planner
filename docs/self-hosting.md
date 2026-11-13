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

## 2. Get the files

You don't build anything: the Compose files run the published image. Clone the repository
at the release you want (see [Releases](https://github.com/thechainercygnus/character-planner/releases)):

```bash
git clone --branch v0.1.0 https://github.com/thechainercygnus/character-planner.git
cd character-planner
cp .env.example .env
```

## 3. Choose how you'll reach it

| How | Open it at | In `.env` |
|---|---|---|
| This machine only (default) | `http://localhost:8000` | nothing else |
| Your home network | `http://<the server's address>:8000` | `PLANNER_BIND=0.0.0.0` |
| Tailscale (HTTPS on your tailnet) | `https://character-planner.<tailnet>.ts.net` | `TS_AUTHKEY`, optionally `TS_HOSTNAME` |
| Your own reverse proxy with HTTPS, on the same machine | `https://planner.example.com` | nothing else; the proxy forwards to `127.0.0.1:8000` |

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
  shown in game. Forever looks characters up by both, and the planner syncs that
  character.
- `PLANNER_IMAGE`: the release to run, for example
  `PLANNER_IMAGE=ghcr.io/thechainercygnus/character-planner:0.1`. `0.1` follows the
  latest `0.1.x`; `0.1.0` stays put.
- For Tailscale: `TS_AUTHKEY`, and `TS_HOSTNAME` for a name other than `character-planner`.

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

## 8. Alerts (optional)

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

## 9. Logs

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

## 10. Back up and upgrade

**Back up** the database, one file on the volume:

```bash
docker run --rm -v character-planner_planner-data:/data -v "$PWD:/backup" alpine \
  cp /data/character-planner.db /backup/character-planner-$(date +%F).db
```

Do it while the planner is stopped (`docker compose stop`), or accept that the last few
seconds of writes may be missing.

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

## 11. Fair use

- **Battle.net:** the planner uses your own client, within Blizzard's limits for it.
- **Forever Companion:** item and dungeon data comes from
  [Forever Companion](https://forevercompanion.io), a free fan-run service that allows 120
  requests a minute per IP address. The planner paces itself to stay under that. Leave
  `COMPANION_REQUEST_PAUSE` at its default; it's set for that limit.
- **Refreshes:** the worker refreshes data on a schedule. The manual refreshes in the ⋯
  menu are for when something looks out of date, not for running in a loop.

## 12. Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| `Sync failed: Battle.net refused the client ID and secret (HTTP 401)` | A typo in `BNET_CLIENT_ID` or `BNET_CLIENT_SECRET`, or the client was deleted or its secret changed | Copy both again from the developer portal, then `docker compose up -d` |
| The status bar says `Battle.net can't find …`, and the logs say `character … not found` | Name, surname or region doesn't match the character | Check `CHARACTER_NAME`, `CHARACTER_SURNAME` and `BNET_REGION`, then `docker compose up -d` and sync again |
| The status bar says `No Battle.net client`, and `worker.log` says `skipped: no Battle.net client` | `BNET_CLIENT_ID` or `BNET_CLIENT_SECRET` is empty, or Compose didn't read `.env` | Fill in `.env` beside `compose.yaml`, then `docker compose up -d` |
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
