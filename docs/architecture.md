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

## External services

All traffic is outbound, over HTTPS with certificate verification on, through `httpx`.

| Service | Used for | Credentials | Decisions |
| --- | --- | --- | --- |
| Battle.net API | The character (profile, equipment, stats, professions, talents) and static game data (items, recipes, talent trees) | The app's own Client Credentials token, cached in the database; the user login is optional and unused by syncs | [0027](adr/0027-syncs-with-the-app-token.md), [0003](adr/0003-item-data-from-search-and-manual-entry.md), [0010](adr/0010-enchants-from-recipe-data.md), [0025](adr/0025-talent-trees.md), [0031](adr/0031-professions-and-crafted-gear.md) |
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
