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
- use your Battle.net login while it's valid;
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

Choose first: Battle.net sends you back to the planner after you log in, so the address
goes into both `.env` and your Battle.net client.

| How | Open it at | `BNET_REDIRECT_URI` | In `.env` |
|---|---|---|---|
| This machine only (default) | `http://localhost:8000` | `http://localhost:8000/auth/callback` | nothing else |
| Tailscale (HTTPS on your tailnet) | `https://character-planner.<tailnet>.ts.net` | `https://character-planner.<tailnet>.ts.net/auth/callback` | `TS_AUTHKEY`, optionally `TS_HOSTNAME` |
| Your own reverse proxy with HTTPS, on the same machine | `https://planner.example.com` | `https://planner.example.com/auth/callback` | nothing else; the proxy forwards to `127.0.0.1:8000` |

To change the port, set `PLANNER_PORT`.

**On your home network**, without Tailscale or a proxy: set `PLANNER_BIND=0.0.0.0` to
listen on the network as well. Battle.net may refuse a plain `http://` redirect for any
address other than `localhost`. If it does, use Tailscale or a reverse proxy with HTTPS.

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

Each planner uses its owner's own Battle.net API client.

1. Sign in at the [Battle.net developer portal](https://develop.battle.net/access/clients)
   and create a client. The name is up to you.
2. Add your `BNET_REDIRECT_URI` from step 3 as a redirect URL. It must match **exactly**:
   scheme, host, port and path.
3. Copy the **client ID** and **client secret** into `.env`:

   ```
   BNET_CLIENT_ID=...
   BNET_CLIENT_SECRET=...
   ```

Keep `.env` private: the secret is like a password. The planner never logs it.

## 5. Fill in `.env`

Besides the client:

- `BNET_REGION`: your account's region, `us`, `eu`, `kr` or `tw`.
- `BNET_REDIRECT_URI`: from step 3.
- `CHARACTER_NAME` and `CHARACTER_SURNAME`: your character's first name and surname, as
  shown in game. Forever looks characters up by both.
- `PLANNER_IMAGE`: the release to run, for example
  `PLANNER_IMAGE=ghcr.io/thechainercygnus/character-planner:0.1`. `0.1` follows the
  latest `0.1.x`; `0.1.0` stays put.
- For Tailscale: `TS_AUTHKEY`, and `TS_HOSTNAME` for a name other than `character-planner`.

Leave `POST_LOGIN_REDIRECT` and `DATABASE_URL` as they are: Compose sets its own values.

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

## 7. Log in and sync

Open the planner. Before you log in, **Try it without an account** already works: pick a
class and a level to see the best items and dungeons for it.

1. Choose **Log in with Battle.net** and approve. You come back to the planner.
2. Choose **Sync now**. The planner reads your character's profile, gear, talents and
   professions.
3. **The first sync also loads item, enchant and talent data in the background.** That
   takes a few minutes, and the status bar says so (ADR 0024). Upgrades and Dungeons fill
   in when it's done.

From then on, the worker syncs every 6 hours (`SYNC_EVERY_HOURS`) while your login is
valid. **Battle.net logins last 24 hours with no way to renew them,** so log in again when
you want fresh data. The worker's log then says
`skipped: no valid login (none yet, or it expired); log in to resume syncs`.

## 8. Alerts (optional)

The planner can post to a Discord channel:
- after a sync: level-ups, a gear target reached or now in reach, and new upgrades worth
  having;
- about your login: 2 hours before it expires, and when it has.

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
| Battle.net shows an error about the redirect URI after **Log in** | `BNET_REDIRECT_URI` and the client's redirect URL differ: `http` versus `https`, a port, or a trailing slash | Make them identical, then `docker compose up -d` to apply `.env` |
| `BNET_CLIENT_ID / BNET_CLIENT_SECRET are not set` | `.env` has no client, or Compose didn't read it | Fill in `.env` beside `compose.yaml`, then `docker compose up -d` |
| `Unknown or expired login state` | The login took over 10 minutes, or the planner restarted mid-login | Choose **Log in** again |
| After a sync, nothing shows, and `server.log` says `failed: profile (404)` | Name, surname or region doesn't match the character | Check `CHARACTER_NAME`, `CHARACTER_SURNAME` and `BNET_REGION`, then sync again |
| `worker.log` says `skipped: no valid login` | The 24-hour login expired | Log in again |
| Upgrades and Dungeons stay empty after the first sync | Item data is still loading | Wait for the status bar's note to clear. `server.log` shows progress every 50 items |
| `migrate` exited with an error, and the app doesn't start | The schema update failed | `docker compose logs migrate`. Restore your backup if needed, and [report it](https://github.com/thechainercygnus/character-planner/issues) |
| `pull access denied` for the image | A typo in `PLANNER_IMAGE`, or a version that doesn't exist | Copy the image name from the release notes |

For anything else, open an
[issue](https://github.com/thechainercygnus/character-planner/issues) with the relevant log
lines. Report security problems privately, as [SECURITY.md](../SECURITY.md) explains.

## Running from source

To change the code, build the image from your checkout instead: leave `PLANNER_IMAGE`
unset and use `docker compose up -d --build`. [CONTRIBUTING.md](../CONTRIBUTING.md) covers
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
