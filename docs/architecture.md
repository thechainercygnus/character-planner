# Architecture

One page on how the planner fits together. Each part links to the decision record (ADR)
that explains why it's built that way.

## Components

```
                 browser
                    │  HTTPS: Tailscale or your proxy; HTTP on localhost by default
┌───────────────────┼───────────────────────────────────────────────┐
│ one image         ▼                                               │
│   ┌─────────────────────────┐        ┌──────────────────────────┐ │
│   │ API (FastAPI)           │        │ worker                   │ │
│   │ /api, /auth, and the    │        │ scheduled sync, refreshes│ │
│   │ built web app at /      │        │ and the alert outbox     │ │
│   └────────────┬────────────┘        └────────────┬─────────────┘ │
│                └───────────────┬──────────────────┘               │
│                                ▼                                  │
│                  SQLite on a volume (WAL, migrations)             │
└────────────────────────────────┼──────────────────────────────────┘
                                 │ HTTPS, outbound only
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   Battle.net (Blizzard)   Forever Companion     Discord webhooks
   profile + game data     dungeons, items,      alerts
                           quests, rares
```

| Part | What it does | Code | Decisions |
| --- | --- | --- | --- |
| API | FastAPI app: data routes under `/api`, the optional Battle.net login under `/auth`, and the built web app at `/` | `app.py` | [0001](adr/0001-python-backend.md), [0020](adr/0020-self-hosted-and-managed.md) |
| Worker | Runs the sync and the static-data refreshes on a schedule, and sends queued alerts | `worker.py`, `jobs.py` | [0011](adr/0011-docker-compose-with-a-worker.md), [0024](adr/0024-first-loads-and-leases.md) |
| Web app | React with TanStack Query, built by Vite into `frontend/dist` and served by the API | `frontend/src` | [0017](adr/0017-landing-page-and-guest-mode.md) |
| Database | One SQLite file the API and the worker share, in WAL mode, with short write transactions and leases so two refreshes never overlap | `db.py`, `leases.py`, `migrations/` | [0011](adr/0011-docker-compose-with-a-worker.md), [0018](adr/0018-short-write-transactions.md), [0022](adr/0022-schema-migrations.md), [0024](adr/0024-first-loads-and-leases.md) |
| Deployment | One image with three Compose services: `migrate` runs once, then `app` and `worker`. An optional Tailscale sidecar serves it over HTTPS on a tailnet | `Dockerfile`, `compose*.yaml` | [0011](adr/0011-docker-compose-with-a-worker.md), [0026](adr/0026-releases.md) |

## Modules

Every module in `src/character_planner/`, with the issue and ADR behind it. A new
module adds its line here.

- `blizzard/`: OAuth and the API client (raw JSON in, status always reported)
- `db.py`: SQLModel tables (`Character`, `Snapshot`, `StoredToken`...); `init_db` runs the migrations in `migrations/` (ADR 0022)
- `characters.py`: tracked characters; `.env` can seed the first, which adopts rows from before #14, and without `CHARACTER_NAME` the planner starts blank and characters are added in the app (#206, ADR 0049); snapshots, progress history and the settings edited in the app belong to one, and every reader takes a `character_id`; `db.owned`/`save_owned` read and write a character's settings row; a request picks its character with the `X-Character-Id` header, else the first (ADR 0036)
- `classes.py` + `data/curated/classes/*.yaml`: shipped defaults per class, chosen by the synced class; the Warrior's are the original curated files (ADR 0023)
- `builds.py` + `data/curated/builds.yaml`: builds, what a character is for: a weight preset, a role and optionally a talent order, curated per class (`builds:` in each class file; the Warrior's in builds.yaml), picked per character in `CharacterBuild`; edits show as customised; the guild view's role is the member's choice, then the build's, then the spec's (#216, ADR 0060)
- `curated.py` + `data/curated/*.yaml`: hand-maintained defaults (targets, stat weights, rules); edits made in the app live in the database
- `scoring.py`: gear scores from editable stat weights (ADR 0005) in named presets (ADR 0013); shipped presets in `data/curated/stat_weights.yaml` and `weight_presets.yaml`
- `items.py`: item catalog (Battle.net item search + icons), cached in SQLite (ADR 0003)
- `companion.py`: Forever Companion source, GET /items/{id} only (ADR 0004); spec in `docs/vendor/`
- `dungeons.py`: Forever Companion dungeons: drop tables and quest rewards (ADR 0006)
- `pool.py`: item pool built from dungeon data, level window, target id resolution (ADR 0006)
- `rares.py`: rares and their drops, a third pool source; merged by id because the list's cache ignores filters (ADR 0029)
- `crafting.py` + `data/curated/professions.yaml`: profession ranks and crafted gear from known recipes, a pool source (ADR 0031)
- `recipe_book.py`: the Professions tab's recipes, known and not learned yet, from each profession's skill tier (`SkillTier`) and every listed recipe's details, fetched in the background after a sync under the `recipes` lease (#226, ADR 0054)
- `lookahead.py`: what the next levels bring, built from the gear, talent, class quest, profession and dungeon views (ADR 0032)
- `class_quests.py`: the class quest checklist by class, faction, race and level; done marks set in the app (ADR 0030)
- `quests.py`: quest chains for quest rewards; steps no dungeon describes fetched by id, zone quests only named (ADR 0028)
- `retention.py`: Blizzard data kept at most 30 days: pruning, refresh-before-expiry ages, archived Progress points, forgetting a character Battle.net no longer has (ADR 0034, #131)
- `progress.py`: progress over time rebuilt from snapshots: points, gear changes, level-ups (ADR 0008)
- `talents.py`: the talent plan compared with synced talents (ADR 0009), matched by talent id; default in `data/curated/talent_plan.yaml`
- `talent_trees.py`: Forever's talent trees from Blizzard's game data, and the plan rules (prerequisites, points per row); the frontend's twin is `frontend/src/talentRules.ts` (ADR 0025)
- `enchants.py`: enchant catalog from Blizzard recipe data and per-slot enchant advice (ADR 0010); gaps filled in `data/curated/enchants.yaml`
- `recommend.py`: best upgrades per slot and dungeons worth running, from the pool (ADR 0007)
- `enchant_corrections.py`: corrections to `enchants.yaml` made in the app (material levels, crafted effects, per_slot), applied in `get_enchant_data` (ADR 0033)
- `rules.py`: the Upgrades rules edited in the app; `data/curated/recommend.yaml` is the default (ADR 0016)
- `guest.py`: guest mode, recommendations for a class and level from the shipped defaults; reads no character data, stores nothing (ADR 0017)
- `erase.py`: deletes everything stored for the character, from the Privacy page or `character-planner-db erase --yes`; every table but the shared game-data caches in `SHARED` (#133, ADR 0034)
- `queue.py`: background jobs on Redis with RQ, optional (`REDIS_URL`); one sync per character, polled with `GET /api/sync`, and the admin's refreshes, shown in the status's `refreshing`; `character-planner-jobs` (#17, ADR 0039). Manual refreshes have a cooldown (`leases.cool_down`)
- `metrics.py`: `/api/readyz` (database at the newest migration, the queue) and Prometheus metrics at `/api/metrics`, off unless `METRICS_TOKEN` is set (#17, ADR 0041)
- `upstream.py`: the upstream budget; every Battle.net and Forever Companion client comes from `upstream.client()`, which waits for room (shared through Redis with `REDIS_URL`); tests run with no budget (#17, ADR 0040)
- `users.py`: users, server-side sessions and per-user tokens when `PLANNER_USERS` is on; the first sign-in is the admin; characters belong to a user and requests resolve them through the signed-in user (#16, ADR 0037)
- `account_page.py`: the account page's view (`GET /api/account`): one user's characters with last sync, guild, guild view and game-data import; without users, every character and no account (#217, ADR 0058)
- `export.py`: everything stored for one user, as JSON in a zip, for an access request: the admin area's export, and the account page's to come (#238, #217, ADR 0056)
- `backup.py`: encrypted backups: a logical JSON dump without Blizzard's data or secrets (`EXCLUDED`), age-encrypted to a public key, kept in S3-compatible storage, pruned to `BACKUP_KEEP`; the worker backs up when due; restore into an empty database at the same revision (#240, ADR 0061)
- `admin_log.py`: the admin action log: who deleted, exported, changed a role or corrected shared data, as account ids, never the data; outlives deleted accounts, kept a year (#238, ADR 0056)
- `signups.py`: sign-ups open or closed (the app's choice in `InstanceSetting` wins over `PLANNER_SIGNUPS` once made) and one-use invites, hashed, held from the link's `#invite=` fragment behind a random cookie reference until the sign-in callback spends them (#239, ADR 0057)
- `health.py`: the admin area's instance health: database, queue and its worker's heartbeat, failed jobs (redacted, kinds only), the upstream budget and the catalogs' last refreshes; read directly, so it works without `METRICS_TOKEN`; the scheduled worker's failures are kept in `instancesetting` (#241)
- `roles.py`: roles (admin, superuser, user) with permissions as data in the `role` table; routes check a permission by name through `app.ROUTE_PERMISSIONS`, never a role; the admin area's account list (#237, ADR 0055)
- `guild.py` + `data/curated/roles.yaml`: the guild view; opted-in members of a guild see each other's needs and a group dungeon ranking, users on only; roles from specs (#18, ADR 0042); the guild's alert channel, a webhook any member sets, with each member's shared alerts (#163, ADR 0046); your guilds: a picker over every guild your characters are in, joining with several at once, and alts shown as one player only on opt-in (`GuildAltGrouping`, #215, ADR 0059)
- `account.py`: the signed-in account's characters (`/profile/user/wow`), to pick ones to track; fetched each time, never stored (#15, ADR 0036)
- `choices.py`: items dismissed in the app, on top of `exclude_item_ids` (ADR 0012)
- `targets.py`: gear targets edited in the app and pins from the Upgrades tab; `gear_targets.yaml` is the default (ADR 0014); per-target levels (ADR 0015)
- `savedvariables.py`: reads WoW SavedVariables files, a Lua subset, without executing anything; hard limits on size, depth, values and strings (#183, ADR 0047)
- `gamedata.py`: the addon's data (`addon/SCHEMA.md`) as strict models by schema version; `read_export` turns an upload into `GameData` (#183, ADR 0047); `import_for` checks it's the selected character's and keeps the newest in `GameDataImport`, served by `/api/game-data` (#184)
- `links.py`: Wowhead links, built here only: a source's own link, else one from the item id; every view model naming an item has a `wowhead`, which the frontend's `ItemLink` shows (#225, ADR 0053)
- `fields.py`: defensive JSON readers used by all parsers
- `views.py`: the only code that reads API response shapes; typed views for the frontend
- `summary.py`: Markdown rendering of those views, for pasting into a chat
- `notify.py`: alerts to Discord webhooks: destinations, change detection after a sync, an outbox the worker sends (ADR 0021); each user's webhooks are their own and get only their characters' alerts, system alerts the admin's (#164, ADR 0045)
- `discord.py`: Discord DMs from the instance's bot: account linking (`identify`), the `discord_dm` destination, refusals pause it; on with the `DISCORD_*` settings (#58, ADR 0043, ADR 0044)
- `signup.py`: the bot's pinned sign-up message in `DISCORD_SIGNUP_CHANNEL_ID`: found by its author and footer marker among the channel's pins, edited or posted and pinned; refusals reported, never retried (#192, ADR 0048)
- `announce.py`: at the worker's start, posts a new full release to `DISCORD_SIGNUP_CHANNEL_ID` once, the last one announced kept in `InstanceSetting`; the first start records only, pre-releases skipped, refusals logged and not retried (#254)
- `logs.py`: logging for the API and the worker: console, rotating files with `LOG_DIR`, request ids, redaction of secrets in every line (ADR 0019)
- `tokens.py`: the app's own Battle.net token (Client Credentials), cached and renewed; syncs and every refresh use it, so no login is needed (ADR 0027)
- `leases.py`: one-at-a-time leases for long refreshes, shared by the API and the worker (ADR 0024)
- `jobs.py`: sync and pool refresh, shared by the API and the worker
- `worker.py`: scheduled jobs beside the API (ADR 0011); `Dockerfile`, `compose*.yaml` and `docs/self-hosting.md` deploy both
- `app.py`: FastAPI routes, built by `create_app()`. Data routes live under `/api`, the optional Battle.net login under `/auth`; a built frontend in `frontend/dist` is served at `/`

## External services

All traffic is outbound, over HTTPS with certificate verification on, through `httpx`.

| Service | Used for | Credentials | Decisions |
| --- | --- | --- | --- |
| Battle.net API | The character (profile, equipment, stats, professions, talents) and static game data (items, recipes, talent trees; the names and icons of items in an imported addon file) | The app's own Client Credentials token, cached in the database; the user login is optional and unused by syncs | [0027](adr/0027-syncs-with-the-app-token.md), [0003](adr/0003-item-data-from-search-and-manual-entry.md), [0010](adr/0010-enchants-from-recipe-data.md), [0025](adr/0025-talent-trees.md), [0031](adr/0031-professions-and-crafted-gear.md) |
| Forever Companion | Dungeons, drops, quests, rares, class quests and item details | None (a keyless public API) | [0004](adr/0004-forever-companion-by-item-id.md), [0006](adr/0006-item-pool-from-dungeon-data.md), [0028](adr/0028-quest-chains.md), [0029](adr/0029-rares.md), [0030](adr/0030-class-quests.md) |
| Discord | Alerts posted to webhooks the user adds | The webhook URL, stored in the database | [0021](adr/0021-notifications.md) |

## How data flows

1. **Sync.** The worker (or **Sync now**) fetches the character's endpoints and stores
   each response as it came, failures included, as a snapshot
   ([0002](adr/0002-raw-snapshots-first.md)). Only `views.py` reads those shapes, so an
   API change is fixed in one place.
2. **Static data.** Refreshes cache Forever Companion's dungeons, rares, class quests,
   quest steps and item details, and Blizzard's recipes, talent trees and crafted items.
   Each is stored raw and parsed on read. Some lists are merged by id, because their
   upstream cache can serve a filtered subset ([0029](adr/0029-rares.md)).
3. **The item pool.** Dungeon drops, quest rewards (with their chains), rare drops and
   the character's crafted gear make one pool of candidate items
   ([0006](adr/0006-item-pool-from-dungeon-data.md)).
4. **Recommendations.** Items are scored with editable stat weights
   ([0005](adr/0005-gear-scoring-with-editable-weights.md),
   [0013](adr/0013-stat-weight-presets.md)) under the Upgrades rules
   ([0016](adr/0016-upgrades-rules-edited-in-the-app.md)), giving upgrades per slot and
   dungeons worth running ([0007](adr/0007-propose-gear-from-the-item-pool.md)).
5. **Plans.** Gear targets ([0014](adr/0014-gear-targets-edited-in-the-app.md),
   [0015](adr/0015-per-target-levels.md)), the talent plan
   ([0009](adr/0009-hand-entered-talent-plan.md)), class quests, profession ranks and the
   look-ahead ([0032](adr/0032-look-ahead.md)) compare the character with what's planned.
6. **Alerts.** After a sync, changes worth knowing go into an outbox, and the worker
   sends them to Discord with retries ([0021](adr/0021-notifications.md)).

## Defaults and edits

Shipped defaults live in `data/curated/`, per class
([0023](adr/0023-class-defaults.md)). Anything edited in the app (targets, weights,
rules, the talent plan, enchant corrections, done marks, dismissed items) is stored in
the database on top of them, so a release can improve a default the user never changed
([0033](adr/0033-enchant-corrections.md)).

## Cross-cutting

- **Logging:** console and rotating files, a request id on every line, and secrets
  redacted in every line ([0019](adr/0019-logging.md)).
- **Migrations:** Alembic runs on every start, so any older database comes up to date
  ([0022](adr/0022-schema-migrations.md)).
- **Releases:** tagged, scanned, signed and attested images on GHCR
  ([0026](adr/0026-releases.md)).
- **Security:** the trust boundaries, threats and their mitigations are in the
  [assurance case](assurance-case.md).
