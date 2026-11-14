# API reference

The planner's HTTP API, generated from its OpenAPI schema by
`uv run character-planner-api-docs`; don't edit this page by hand. A running instance
serves the same reference interactively at `/docs`, and the raw schema is
[openapi.json](_static/openapi.json).

- Data routes are under `/api`; the optional Battle.net login is under `/auth`.
- Requests that change something (`POST`, `PUT`, `PATCH`, `DELETE`) need the header
  `X-Requested-With: character-planner`, as the web app sends it; reads don't.
- The API answers only to the host names it's configured for (`PLANNER_HOSTS`).
- Errors come back as JSON with a `detail` field; invalid input gets 422.

## Endpoints

## `about`

### `GET /api/about`

What the page footer shows (#43): the data credits, the source link (AGPL) and the version. Needs no character data, so guest mode has it too.

**200:** [About](#schema-about)

## `account`

### `DELETE /api/account`

Delete the signed-in user and everything stored for them (#16, ADR 0037): their characters with all their data and settings, sessions and Battle.net token. Only with users on; the admin can't while others remain (409).

**200:** no body

### `GET /api/account/characters`

The characters on the signed-in Battle.net account (#15), to pick ones to track. Fetched each time and never stored: the list names every character on the account (ADR 0034). Needs the optional Battle.net sign-in.

**200:** [AccountCharacters](#schema-accountcharacters)

## `character`

### `GET /api/character`

Character

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [CharacterView](#schema-characterview)

### `DELETE /api/character`

Stop tracking the character and delete everything stored for it (#133, #14): snapshots, history, plans and settings edited in the app. Other characters and shared game data stay. With none left, the next start tracks the character .env names again.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [Erased](#schema-erased)

## `characters`

### `GET /api/characters`

The tracked characters, for the header's switcher (#14): the signed-in user's when users are on. Requests pick one with X-Character-Id; without it they get default_id, the first.

**200:** [CharacterList](#schema-characterlist)

### `POST /api/characters`

Track another character. Sync it (with its X-Character-Id) to fetch its data.

**Body:** [NewCharacter](#schema-newcharacter)

**201:** [CharacterSummary](#schema-charactersummary)

## `choices`

### `GET /api/choices`

Items dismissed in the app, newest first (ADR 0012).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** list of [ItemChoiceView](#schema-itemchoiceview)

### `PUT /api/choices/{item_id}`

Dismiss an item: never suggest it. Pinning is POST /api/targets/pins.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [ChoiceUpdate](#schema-choiceupdate)

**200:** list of [ItemChoiceView](#schema-itemchoiceview)

### `DELETE /api/choices/{item_id}`

Suggest a dismissed item again.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** list of [ItemChoiceView](#schema-itemchoiceview)

## `class-quests`

### `GET /api/class-quests`

The synced character's class quests: missed, now, soon, later and done (#8).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [ClassQuestChecklist](#schema-classquestchecklist)

### `PUT /api/class-quests/{quest_id}`

Mark a class quest done, or not done.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `quest_id` | path | string (pattern ^[a-z0-9-]{1,100}$) | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [ClassQuestUpdate](#schema-classquestupdate)

**200:** [ClassQuestChecklist](#schema-classquestchecklist)

## `enchants`

### `GET /api/enchants`

Every enchant recipe that maps to a gear slot, with parsed effects.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `include_sod` | query | boolean | no | false |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** list of [EnchantOption](#schema-enchantoption)

### `GET /api/enchants/corrections`

Corrections to enchants.yaml made in the app, and the shipped values (#36).

**200:** [CorrectionsView](#schema-correctionsview)

### `PUT /api/enchants/corrections/crafted/{item_id}`

Add or fix the effect of a crafted enchant (a scope, an armor kit).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |

**Body:** [EffectsUpdate](#schema-effectsupdate)

**200:** [CorrectionsView](#schema-correctionsview)

### `DELETE /api/enchants/corrections/crafted/{item_id}`

Go back to the shipped effect, or none.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |

**200:** [CorrectionsView](#schema-correctionsview)

### `PUT /api/enchants/corrections/materials/{item_id}`

Correct the level a material is commonly found from.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |

**Body:** [LevelUpdate](#schema-levelupdate)

**200:** [CorrectionsView](#schema-correctionsview)

### `DELETE /api/enchants/corrections/materials/{item_id}`

Go back to the shipped level (or the item's own).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |

**200:** [CorrectionsView](#schema-correctionsview)

### `PUT /api/enchants/corrections/per-slot`

How many enchants to list per slot.

**Body:** [PerSlotUpdate](#schema-perslotupdate)

**200:** [CorrectionsView](#schema-correctionsview)

### `DELETE /api/enchants/corrections/per-slot`

Go back to the shipped number.

**200:** [CorrectionsView](#schema-correctionsview)

### `GET /api/enchants/recommendations`

Best enchants in reach per slot, against the one on now (ADR 0010).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [EnchantAdvice](#schema-enchantadvice)

### `POST /api/enchants/refresh`

Enchant recipes from Blizzard's profession data, plus their reagents and crafted items from Forever Companion (ADR 0010).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `force` | query | boolean | no | false |

**200:** [RecipeRefresh](#schema-reciperefresh)

## `gear`

### `GET /api/gear`

Gear

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [GearPlan](#schema-gearplan)

## `guest`

### `GET /api/guest`

What guest mode offers: classes with shipped defaults, and their presets.

**200:** [GuestOptions](#schema-guestoptions)

### `GET /api/guest/recommendations`

Guest mode (ADR 0017): the best items per slot and dungeons for a class and level, from the shipped rules and weights. Reads no character data; stores nothing.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `level` | query | integer (minimum 1, maximum 80) | yes |  |
| `class` | query | string | no | "warrior" |
| `faction` | query | `alliance` \\| `horde` | no | "alliance" |
| `preset` | query | string or null | no |  |

**200:** [Recommendations](#schema-recommendations)

## `healthz`

### `GET /api/healthz`

Healthz

**200:** map of string

## `items`

### `POST /api/items/refresh`

Refresh item data from every source. force=true refetches everything. Source failures are reported in `errors` rather than failing the request.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `force` | query | boolean | no | false |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [RefreshResult](#schema-refreshresult)

## `logout`

### `POST /api/logout`

Sign out: the session stops working at once (ADR 0037).

**204:** no body

## `look-ahead`

### `GET /api/look-ahead`

What each of the next `levels` levels brings (#4): dungeons opening, gear targets, talent points, class quests and profession ranks.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `levels` | query | integer (minimum 1, maximum 10) | no | 5 |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [LookAhead](#schema-lookahead)

## `me`

### `GET /api/me`

Whether users are on, and who's signed in (ADR 0037). Public, so the page knows to offer the sign-in.

**200:** [Me](#schema-me)

## `notifications`

### `GET /api/notifications`

Alert destinations (webhook URLs masked), the alerts on offer, recent sends.

**200:** [NotificationsView](#schema-notificationsview)

### `POST /api/notifications/destinations`

Add a Discord webhook destination (#12).

**Body:** [NewDestination](#schema-newdestination)

**201:** [NotificationsView](#schema-notificationsview)

### `PATCH /api/notifications/destinations/{destination_id}`

Patch Destination

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `destination_id` | path | integer | yes |  |

**Body:** [DestinationUpdate](#schema-destinationupdate)

**200:** [NotificationsView](#schema-notificationsview)

### `DELETE /api/notifications/destinations/{destination_id}`

Delete Destination

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `destination_id` | path | integer | yes |  |

**200:** [NotificationsView](#schema-notificationsview)

### `POST /api/notifications/destinations/{destination_id}/test`

Send a test message to the destination now.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `destination_id` | path | integer | yes |  |

**200:** [SendResult](#schema-sendresult)

## `pool`

### `GET /api/pool`

Dungeon drops and quest rewards for the character's level window.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [PoolView](#schema-poolview)

### `POST /api/pool/refresh`

Refresh dungeon drop tables and quest rewards, then item details for a level window: `level`'s (guest mode asks for its own), else the character's, else the whole pool. The first run takes a few minutes (paced under Forever Companion's rate limit); `uv run character-planner-pool` does the same with progress output.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `force` | query | boolean | no | false |
| `level` | query | integer (minimum 1, maximum 80) or null | no |  |

**200:** [PoolRefresh](#schema-poolrefresh)

## `professions`

### `GET /api/professions`

Each synced profession: skill, rank, the next rank and crafted gear (#10).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [ProfessionsView](#schema-professionsview)

## `progress`

### `GET /api/progress`

One point per sync, plus gear changes and level-ups (ADR 0008).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [Progress](#schema-progress)

## `recommendations`

### `GET /api/recommendations`

Best upgrades in reach for each slot, from the item pool (ADR 0007).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [Recommendations](#schema-recommendations)

## `rules`

### `GET /api/rules`

The Upgrades rules, their defaults, and what the editor can offer (ADR 0016).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [RulesView](#schema-rulesview)

### `PUT /api/rules`

Replace the Upgrades rules.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [EditedRules](#schema-editedrules)

**200:** [RulesView](#schema-rulesview)

### `DELETE /api/rules`

Go back to data/curated/recommend.yaml.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [RulesView](#schema-rulesview)

## `snapshots`

### `GET /api/snapshots/latest`

Latest

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** object

### `POST /api/snapshots/manual`

Fallback for data the API doesn't return: store it in the same shape, for the current character.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [ManualSnapshot](#schema-manualsnapshot)

**201:** map of integer or null

## `status`

### `GET /api/status`

Status

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** object

## `summary.md`

### `GET /api/summary.md`

Summary

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** no body

## `sync`

### `POST /api/sync`

Pull every endpoint and store each response, failures included. Then look up any target items not in the item catalog yet. That step is best-effort: a catalog failure never fails the sync. On a fresh instance, the item pool and enchant data then load in the background (#87). At most once per SYNC_COOLDOWN_MINUTES per character (429 with Retry-After), to share the Battle.net budget (#17). With REDIS_URL set, the sync is queued (202, a SyncState) and GET /api/sync follows it (ADR 0039).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** map of integer or [SyncState](#schema-syncstate)

### `GET /api/sync`

The character's queued sync (ADR 0039): queued, started, finished with each endpoint's status, or failed. "idle" when there's none, or no queue.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [SyncState](#schema-syncstate)

## `talents`

### `GET /api/talents`

The talent plan compared with the synced talents (ADR 0009).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [TalentPlanView](#schema-talentplanview)

### `PUT /api/talents/plan`

Replace the talent plan. With the talent trees loaded, a plan that breaks their rules (unknown talents, prerequisites, points per row) is refused (#88).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [TalentPlan](#schema-talentplan)

**200:** [TalentPlanView](#schema-talentplanview)

### `DELETE /api/talents/plan`

Go back to data/curated/talent_plan.yaml.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [TalentPlanView](#schema-talentplanview)

### `POST /api/talents/refresh`

Fetch the synced class's talent trees and icons again.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [TalentRefresh](#schema-talentrefresh)

### `GET /api/talents/tree`

The synced class's talent trees (#88). `tree` is null until they're loaded: after the first sync, in the background.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [TalentTreeView](#schema-talenttreeview)

## `targets`

### `GET /api/targets`

The gear targets in use: edited in the app, or gear_targets.yaml (ADR 0014).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [GearTargets](#schema-geartargets)

### `PUT /api/targets`

Replace the gear targets. Priority follows each slot's order.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [EditedTargets](#schema-editedtargets)

**200:** [GearTargets](#schema-geartargets)

### `DELETE /api/targets`

Go back to data/curated/gear_targets.yaml.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [GearTargets](#schema-geartargets)

### `POST /api/targets/pins`

Pin a pool item as a target ("Make target").

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [Pin](#schema-pin)

**200:** [GearTargets](#schema-geartargets)

### `DELETE /api/targets/pins/{item_id}`

Take the pin off a target ("Unpin"); it stays a target.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `item_id` | path | integer (exclusiveMinimum 0) | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [GearTargets](#schema-geartargets)

## `weights`

### `GET /api/weights`

The active preset's weights, its defaults and every preset (ADR 0013).

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [WeightsView](#schema-weightsview)

### `PUT /api/weights`

Replace the active preset's weights. Stats left out fall back to their default.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [WeightsUpdate](#schema-weightsupdate)

**200:** [WeightsView](#schema-weightsview)

### `DELETE /api/weights`

Reset the active shipped preset to its curated file.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [WeightsView](#schema-weightsview)

### `PUT /api/weights/active`

Switch presets: every score uses the active one.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [PresetChoice](#schema-presetchoice)

**200:** [WeightsView](#schema-weightsview)

### `POST /api/weights/presets`

Save weights as a preset of your own ("Save as") and switch to it.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [NewPreset](#schema-newpreset)

**201:** [WeightsView](#schema-weightsview)

### `PATCH /api/weights/presets/{key}`

Rename a preset of your own.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `key` | path | string | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**Body:** [PresetRename](#schema-presetrename)

**200:** [WeightsView](#schema-weightsview)

### `DELETE /api/weights/presets/{key}`

Delete a preset of your own; if it was active, Leveling tank takes over.

| Parameter | In | Type | Required | Default |
| --- | --- | --- | --- | --- |
| `key` | path | string | yes |  |
| `X-Character-Id` | header | integer (exclusiveMinimum 0) or null | no |  |

**200:** [WeightsView](#schema-weightsview)

## `auth`

### `GET /auth/callback`

Callback

**200:** no body

### `GET /auth/login`

Login

**200:** no body

## Schemas

(schema-about)=
### About

| Field | Type | Required |
| --- | --- | --- |
| `version` | string | yes |
| `source_url` | string | yes |
| `data` | [DataCredit](#schema-datacredit) | yes |
| `operator_contact` | string | no |

(schema-accountcharacter)=
### AccountCharacter

| Field | Type | Required |
| --- | --- | --- |
| `blizzard_id` | integer or null | yes |
| `name` | string | yes |
| `surname` | string | yes |
| `slug` | string | yes |
| `region` | string | yes |
| `character_class` | string or null | yes |
| `race` | string or null | yes |
| `faction` | string or null | yes |
| `level` | integer or null | yes |
| `tracked` | boolean | no |

(schema-accountcharacters)=
### AccountCharacters

| Field | Type | Required |
| --- | --- | --- |
| `characters` | list of [AccountCharacter](#schema-accountcharacter) | yes |

(schema-alertinfo)=
### AlertInfo

| Field | Type | Required |
| --- | --- | --- |
| `kind` | `level_up` \\| `target_reached` \\| `target_in_reach` \\| `new_upgrade` \\| `job_failed` \\| `upstream_errors` | yes |
| `audience` | `user` \\| `system` | yes |
| `label` | string | yes |

(schema-candidate)=
### Candidate

| Field | Type | Required |
| --- | --- | --- |
| `item` | [PoolItem](#schema-poolitem) | yes |
| `score_gain` | number | yes |
| `item_level_delta` | integer or null | no |
| `armor_delta` | integer or null | no |
| `stat_deltas` | map of integer | no |
| `usable_now` | boolean | yes |
| `is_target` | boolean | no |
| `pinned` | boolean | no |

(schema-characterlist)=
### CharacterList

| Field | Type | Required |
| --- | --- | --- |
| `characters` | list of [CharacterSummary](#schema-charactersummary) | yes |
| `default_id` | integer or null | yes |

(schema-charactersummary)=
### CharacterSummary

A tracked character, for the header's switcher (#14).

| Field | Type | Required |
| --- | --- | --- |
| `id` | integer | yes |
| `region` | string | yes |
| `slug` | string | yes |
| `name` | string | yes |
| `surname` | string | yes |
| `character_class` | string or null | yes |
| `race` | string or null | yes |
| `faction` | string or null | yes |
| `level` | integer or null | yes |

(schema-characterview)=
### CharacterView

| Field | Type | Required |
| --- | --- | --- |
| `name` | string or null | no |
| `surname` | string or null | no |
| `level` | integer or null | no |
| `race` | string or null | no |
| `character_class` | string or null | no |
| `guild` | string or null | no |
| `equipped_item_level` | number or null | no |
| `gear_slots_filled` | integer | no |
| `captured_at` | string or null | no |
| `stats` | [Stats](#schema-stats) or null | no |
| `professions` | list of [Profession](#schema-profession) | no |
| `specialization` | [Specialization](#schema-specialization) or null | no |
| `equipment` | list of [EquippedItem](#schema-equippeditem) | no |

(schema-choiceupdate)=
### ChoiceUpdate

| Field | Type | Required |
| --- | --- | --- |
| `choice` | string | yes |
| `name` | string (minLength 1, maxLength 120) | yes |

(schema-classquestchecklist)=
### ClassQuestChecklist

| Field | Type | Required |
| --- | --- | --- |
| `class_name` | string or null | yes |
| `level` | integer or null | yes |
| `soon_levels` | integer | no |
| `listed` | integer | yes |
| `rows` | list of [ClassQuestRow](#schema-classquestrow) | yes |

(schema-classquestrow)=
### ClassQuestRow

| Field | Type | Required |
| --- | --- | --- |
| `id` | string | yes |
| `class_key` | string | yes |
| `level` | integer | yes |
| `name` | string | yes |
| `faction` | string | no |
| `races` | list of string or null | no |
| `giver` | string or null | no |
| `location` | string or null | no |
| `reward` | string or null | no |
| `essential` | boolean | no |
| `done` | boolean | no |
| `status` | `done` \\| `missed` \\| `now` \\| `soon` \\| `later` | yes |

(schema-classquestupdate)=
### ClassQuestUpdate

| Field | Type | Required |
| --- | --- | --- |
| `done` | boolean | yes |

(schema-classtree)=
### ClassTree

| Field | Type | Required |
| --- | --- | --- |
| `class_name` | string | yes |
| `tree_id` | integer | yes |
| `specs` | list of [SpecTree](#schema-spectree) | yes |

(schema-correctionsview)=
### CorrectionsView

What's corrected, what ships, and the effect names a correction may use.

| Field | Type | Required |
| --- | --- | --- |
| `corrections` | [EnchantCorrections](#schema-enchantcorrections) | yes |
| `shipped` | [EnchantData](#schema-enchantdata) | yes |
| `effect_names` | list of string | yes |

(schema-creditlink)=
### CreditLink

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `url` | string | yes |

(schema-currentenchant)=
### CurrentEnchant

| Field | Type | Required |
| --- | --- | --- |
| `text` | string | yes |
| `effects` | map of number | yes |
| `score` | number | yes |

(schema-datacredit)=
### DataCredit

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `url` | string | yes |
| `sources` | list of [CreditLink](#schema-creditlink) | yes |

(schema-destinationupdate)=
### DestinationUpdate

| Field | Type | Required |
| --- | --- | --- |
| `name` | string or null | no |
| `url` | string or null | no |
| `alerts` | list of string or null | no |
| `enabled` | boolean or null | no |

(schema-destinationview)=
### DestinationView

A destination as the app shows it: the URL masked.

| Field | Type | Required |
| --- | --- | --- |
| `id` | integer | yes |
| `name` | string | yes |
| `kind` | string | yes |
| `audience` | `user` \\| `system` | yes |
| `url` | string | yes |
| `alerts` | list of string | yes |
| `enabled` | boolean | yes |
| `last_sent_at` | string or null | yes |
| `last_error` | string or null | yes |

(schema-dungeonupgrade)=
### DungeonUpgrade

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `item` | [PoolItem](#schema-poolitem) | yes |
| `score_gain` | number | yes |
| `source` | [PoolSource](#schema-poolsource) | yes |

(schema-dungeonvalue)=
### DungeonValue

| Field | Type | Required |
| --- | --- | --- |
| `dungeon_id` | string | yes |
| `dungeon` | string | yes |
| `min_level` | integer or null | yes |
| `max_level` | integer or null | yes |
| `total_gain` | number | yes |
| `upgrades` | list of [DungeonUpgrade](#schema-dungeonupgrade) | yes |

(schema-editedrules)=
### EditedRules

Rules as the editor sends them, bounded.

| Field | Type | Required |
| --- | --- | --- |
| `weapon_types` | list of string | yes |
| `armor_types` | list of string | yes |
| `plate_from_level` | integer (minimum 1.0, maximum 80.0) or null | no |
| `mail_from_level` | integer (minimum 1.0, maximum 80.0) or null | no |
| `two_handers` | boolean | no |
| `two_hand_types` | list of string or null | no |
| `off_hand_types` | list of string | yes |
| `dual_wield_from_level` | integer (minimum 1.0, maximum 80.0) or null | no |
| `levels_ahead` | integer (minimum 0.0, maximum 20.0) | yes |
| `per_slot` | integer (minimum 1.0, maximum 10.0) | yes |
| `min_gain` | number (minimum 0.0, maximum 100.0) | yes |

(schema-editedtarget)=
### EditedTarget

A target as the editor sends it: bounded text, the rest as in GearTarget.

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `item` | string (minLength 1, maxLength 120) | yes |
| `source` | string (maxLength 200) | no |
| `item_id` | integer (exclusiveMinimum 0.0) or null | no |
| `level` | integer (minimum 1.0, maximum 80.0) or null | no |
| `priority` | integer or null | no |
| `pinned` | boolean | no |
| `item_level` | integer or null | no |
| `armor_type` | string or null | no |
| `armor` | integer or null | no |
| `stats` | map of integer | no |

(schema-editedtargets)=
### EditedTargets

| Field | Type | Required |
| --- | --- | --- |
| `targets` | list of [EditedTarget](#schema-editedtarget) | yes |

(schema-effectsupdate)=
### EffectsUpdate

| Field | Type | Required |
| --- | --- | --- |
| `effects` | map of number | yes |

(schema-enchantadvice)=
### EnchantAdvice

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `recipes` | integer | yes |
| `rows` | list of [SlotEnchants](#schema-slotenchants) | yes |
| `considered` | integer | yes |
| `unscored` | integer | yes |
| `unknown_level` | integer | yes |
| `missing_effects` | list of [MissingEffect](#schema-missingeffect) | no |
| `per_slot` | integer | no |
| `per_slot_corrected` | boolean | no |

(schema-enchantcorrections)=
### EnchantCorrections

| Field | Type | Required |
| --- | --- | --- |
| `reagent_levels` | map of integer | no |
| `crafted_effects` | map of map of number | no |
| `per_slot` | integer or null | no |

(schema-enchantdata)=
### EnchantData

data/curated/enchants.yaml, with any corrections made in the app on top (#36).

| Field | Type | Required |
| --- | --- | --- |
| `reagent_levels` | map of integer | no |
| `crafted_effects` | map of map of number | no |
| `per_slot` | integer | no |
| `corrected_reagents` | list of integer | no |
| `corrected_crafted` | list of integer | no |
| `per_slot_corrected` | boolean | no |

(schema-enchantoption)=
### EnchantOption

| Field | Type | Required |
| --- | --- | --- |
| `recipe_id` | integer | yes |
| `name` | string | yes |
| `profession` | string | yes |
| `category` | string | yes |
| `slots` | list of string | yes |
| `two_handed` | boolean | no |
| `shield_only` | boolean | no |
| `text` | string or null | yes |
| `effects` | map of number | yes |
| `effects_source` | `description` \\| `curated` \\| `corrected` \\| `equipped` or null | no |
| `temporary` | boolean | no |
| `reagents` | list of [Reagent](#schema-reagent) | yes |
| `crafted_item_id` | integer or null | no |
| `season_of_discovery` | boolean | no |
| `estimated_level` | integer or null | no |

(schema-enchantpick)=
### EnchantPick

| Field | Type | Required |
| --- | --- | --- |
| `option` | [EnchantOption](#schema-enchantoption) | yes |
| `score` | number | yes |
| `score_gain` | number | yes |
| `usable_now` | boolean | yes |
| `can_make` | boolean | yes |

(schema-enchantment)=
### Enchantment

An enchant on an equipped item, as the equipment endpoint reports it.

| Field | Type | Required |
| --- | --- | --- |
| `text` | string | yes |
| `enchantment_id` | integer or null | no |
| `source_item` | string or null | no |
| `source_item_id` | integer or null | no |
| `kind` | string or null | no |

(schema-equippeditem)=
### EquippedItem

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `name` | string | yes |
| `item_id` | integer or null | no |
| `quality` | string or null | no |
| `quality_name` | string or null | no |
| `item_level` | integer or null | no |
| `armor_type` | string or null | no |
| `inventory_type` | string or null | no |
| `armor` | integer or null | no |
| `stats` | list of [ItemStat](#schema-itemstat) | no |
| `dps` | number or null | no |
| `attack_speed` | number or null | no |
| `enchantments` | list of [Enchantment](#schema-enchantment) | no |
| `icon_url` | string or null | no |

(schema-erased)=
### Erased

| Field | Type | Required |
| --- | --- | --- |
| `removed` | map of integer | yes |

(schema-gearchange)=
### GearChange

| Field | Type | Required |
| --- | --- | --- |
| `captured_at` | string | yes |
| `slot` | string | yes |
| `before` | string or null | yes |
| `after` | string or null | yes |
| `item_level_before` | integer or null | no |
| `item_level_after` | integer or null | no |
| `score_change` | number | yes |

(schema-gearplan)=
### GearPlan

Per slot (ADR 0015): the target to go for now, in rows, and what's coming up.

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `rows` | list of [GearRow](#schema-gearrow) | yes |
| `later` | list of [SlotOutlook](#schema-slotoutlook) | no |
| `attributions` | list of map of string | no |
| `targets_customised` | boolean | no |

(schema-gearrow)=
### GearRow

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `equipped` | [EquippedItem](#schema-equippeditem) or null | yes |
| `target` | [GearTarget](#schema-geartarget) | yes |
| `target_info` | [TargetInfo](#schema-targetinfo) or null | yes |
| `reached` | boolean | yes |
| `verdict` | `reached` \\| `upgrade` \\| `sidegrade` \\| `downgrade` \\| `unknown` | yes |
| `item_level_delta` | integer or null | yes |
| `armor_delta` | integer or null | no |
| `stat_deltas` | map of integer | no |
| `score_delta` | number or null | no |
| `verdict_basis` | `score` \\| `item_level` \\| `none` | no |
| `warning` | string or null | yes |
| `level` | integer or null | no |
| `upcoming` | list of [UpcomingTarget](#schema-upcomingtarget) | no |

(schema-geartarget)=
### GearTarget

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `item` | string | yes |
| `source` | string | yes |
| `priority` | integer or null | no |
| `level` | integer or null | no |
| `pinned` | boolean | no |
| `item_id` | integer or null | no |
| `item_level` | integer or null | no |
| `armor_type` | string or null | no |
| `armor` | integer or null | no |
| `stats` | map of integer | no |

(schema-geartargets)=
### GearTargets

One flat list of targets (ADR 0015). Within a slot, list order is priority.

| Field | Type | Required |
| --- | --- | --- |
| `targets` | list of [GearTarget](#schema-geartarget) | yes |

(schema-guestclass)=
### GuestClass

| Field | Type | Required |
| --- | --- | --- |
| `key` | string | yes |
| `name` | string | yes |
| `presets` | list of [PresetOption](#schema-presetoption) | yes |

(schema-guestoptions)=
### GuestOptions

What a guest can choose from.

| Field | Type | Required |
| --- | --- | --- |
| `classes` | list of [GuestClass](#schema-guestclass) | yes |
| `factions` | list of `alliance` \\| `horde` | no |

(schema-httpvalidationerror)=
### HTTPValidationError

| Field | Type | Required |
| --- | --- | --- |
| `detail` | list of [ValidationError](#schema-validationerror) | no |

(schema-itemchoiceview)=
### ItemChoiceView

| Field | Type | Required |
| --- | --- | --- |
| `item_id` | integer | yes |
| `name` | string | yes |
| `choice` | string | yes |
| `created_at` | string | yes |

(schema-itemstat)=
### ItemStat

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `value` | integer | yes |

(schema-levelgroup)=
### LevelGroup

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer | yes |
| `events` | list of [LookAheadEvent](#schema-lookaheadevent) | yes |

(schema-levelup)=
### LevelUp

| Field | Type | Required |
| --- | --- | --- |
| `captured_at` | string | yes |
| `level` | integer | yes |

(schema-levelupdate)=
### LevelUpdate

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer (minimum 1.0, maximum 60.0) | yes |

(schema-lookahead)=
### LookAhead

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `levels` | integer | yes |
| `groups` | list of [LevelGroup](#schema-levelgroup) | yes |

(schema-lookaheadevent)=
### LookAheadEvent

| Field | Type | Required |
| --- | --- | --- |
| `kind` | `dungeon` \\| `target` \\| `talent` \\| `class_quest` \\| `profession` | yes |
| `title` | string | yes |
| `detail` | string or null | no |
| `essential` | boolean | no |
| `pinned` | boolean | no |
| `locked` | boolean | no |
| `link` | string or null | no |

(schema-manualsnapshot)=
### ManualSnapshot

| Field | Type | Required |
| --- | --- | --- |
| `kind` | string | yes |
| `payload` | any | yes |

(schema-me)=
### Me

| Field | Type | Required |
| --- | --- | --- |
| `users` | boolean | yes |
| `signed_in` | boolean | yes |
| `admin` | boolean | yes |
| `signups_open` | boolean | yes |

(schema-missingeffect)=
### MissingEffect

A scope, kit or other crafted enchant in reach whose effect isn't known (#36).

| Field | Type | Required |
| --- | --- | --- |
| `item_id` | integer | yes |
| `recipe` | string | yes |
| `slots` | list of string | yes |

(schema-newcharacter)=
### NewCharacter

A character to track, as Forever looks it up: first name, surname, region.

| Field | Type | Required |
| --- | --- | --- |
| `name` | string (minLength 2, maxLength 12) | yes |
| `surname` | string (minLength 1, maxLength 24) | yes |
| `region` | `us` \\| `eu` \\| `kr` \\| `tw` | yes |

(schema-newdestination)=
### NewDestination

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `url` | string | yes |
| `audience` | `user` \\| `system` | no |
| `alerts` | list of string or null | no |

(schema-newpreset)=
### NewPreset

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `weights` | map of number (minimum -10.0, maximum 10.0) | no |

(schema-nextpoint)=
### NextPoint

| Field | Type | Required |
| --- | --- | --- |
| `talent` | string | yes |
| `talent_id` | integer or null | no |
| `rank` | integer | yes |
| `level` | integer | yes |

(schema-nextrank)=
### NextRank

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `max_skill` | integer | yes |
| `train_at_skill` | integer | yes |
| `train_at_level` | integer | yes |
| `skill_ready` | boolean | yes |
| `level_ready` | boolean | yes |

(schema-notificationsview)=
### NotificationsView

| Field | Type | Required |
| --- | --- | --- |
| `destinations` | list of [DestinationView](#schema-destinationview) | yes |
| `alerts` | list of [AlertInfo](#schema-alertinfo) | no |
| `recent` | list of [RecentView](#schema-recentview) | yes |
| `system_alerts_to_user` | boolean | yes |

(schema-offplan)=
### OffPlan

| Field | Type | Required |
| --- | --- | --- |
| `talent` | string | yes |
| `talent_id` | integer or null | no |
| `current` | integer | yes |
| `planned` | integer | yes |

(schema-perslotupdate)=
### PerSlotUpdate

| Field | Type | Required |
| --- | --- | --- |
| `per_slot` | integer (minimum 1.0, maximum 10.0) | yes |

(schema-pin)=
### Pin

| Field | Type | Required |
| --- | --- | --- |
| `item_id` | integer (exclusiveMinimum 0.0) | yes |
| `slot` | string | yes |

(schema-planstep)=
### PlanStep

| Field | Type | Required |
| --- | --- | --- |
| `talent` | string (minLength 1, maxLength 80) | yes |
| `rank` | integer (minimum 1.0, maximum 10.0) | yes |
| `talent_id` | integer (exclusiveMinimum 0.0) or null | no |

(schema-poolitem)=
### PoolItem

| Field | Type | Required |
| --- | --- | --- |
| `item_id` | integer | yes |
| `name` | string | yes |
| `slot` | string or null | no |
| `quality` | string or null | no |
| `sources` | list of [PoolSource](#schema-poolsource) | no |
| `item_slot` | string or null | no |
| `weapon_type` | string or null | no |
| `item_level` | integer or null | no |
| `required_level` | integer or null | no |
| `armor_type` | string or null | no |
| `armor` | integer or null | no |
| `stats` | map of integer | no |
| `dps` | number or null | no |
| `icon_url` | string or null | no |
| `wowhead` | string or null | no |
| `effective_level` | integer or null | yes |

(schema-poolrefresh)=
### PoolRefresh

| Field | Type | Required |
| --- | --- | --- |
| `dungeons_listed` | integer | no |
| `dungeons_fetched` | integer | no |
| `pool_size` | integer | no |
| `in_window` | integer | no |
| `items_fetched` | integer | no |
| `items_not_found` | list of integer | no |
| `quests_fetched` | integer | no |
| `rares_listed` | integer | no |
| `class_quests_listed` | integer | no |
| `errors` | list of string | no |

(schema-poolsource)=
### PoolSource

| Field | Type | Required |
| --- | --- | --- |
| `kind` | `drop` \\| `quest` \\| `rare` \\| `crafted` | yes |
| `dungeon_id` | string or null | no |
| `dungeon` | string or null | no |
| `min_level` | integer or null | no |
| `max_level` | integer or null | no |
| `detail` | string or null | no |
| `choice` | boolean | no |
| `quest_min_level` | integer or null | no |
| `quest` | [QuestStep](#schema-queststep) or null | no |
| `chain` | list of list of [QuestStep](#schema-queststep) | no |
| `rare_id` | string or null | no |
| `rare` | string or null | no |
| `zone` | string or null | no |
| `spawns` | integer or null | no |
| `elite` | boolean | no |
| `profession` | string or null | no |
| `recipe` | string or null | no |

(schema-poolview)=
### PoolView

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `faction` | string or null | yes |
| `window` | list of any or null | yes |
| `items` | list of [PoolItem](#schema-poolitem) | yes |

(schema-presetchoice)=
### PresetChoice

| Field | Type | Required |
| --- | --- | --- |
| `key` | string | yes |

(schema-presetoption)=
### PresetOption

| Field | Type | Required |
| --- | --- | --- |
| `key` | string | yes |
| `name` | string | yes |

(schema-presetrename)=
### PresetRename

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |

(schema-presetsummary)=
### PresetSummary

| Field | Type | Required |
| --- | --- | --- |
| `key` | string | yes |
| `name` | string | yes |
| `shipped` | boolean | yes |
| `customised` | boolean | yes |

(schema-profession)=
### Profession

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `skill` | integer or null | no |
| `max_skill` | integer or null | no |
| `primary` | boolean | yes |

(schema-professionrow)=
### ProfessionRow

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `primary` | boolean | yes |
| `skill` | integer or null | yes |
| `max_skill` | integer or null | yes |
| `rank` | string or null | yes |
| `next_rank` | [NextRank](#schema-nextrank) or null | yes |
| `note` | string or null | no |
| `known_recipes` | integer | yes |
| `crafted_gear` | list of string | yes |

(schema-professionsview)=
### ProfessionsView

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `professions` | list of [ProfessionRow](#schema-professionrow) | yes |

(schema-progress)=
### Progress

| Field | Type | Required |
| --- | --- | --- |
| `points` | list of [ProgressPoint](#schema-progresspoint) | yes |
| `gear_changes` | list of [GearChange](#schema-gearchange) | yes |
| `level_ups` | list of [LevelUp](#schema-levelup) | yes |

(schema-progresspoint)=
### ProgressPoint

| Field | Type | Required |
| --- | --- | --- |
| `captured_at` | string | yes |
| `level` | integer or null | no |
| `item_level` | number or null | no |
| `gear_score` | number or null | no |
| `health` | integer or null | no |
| `armor` | integer or null | no |
| `stamina` | integer or null | no |

(schema-queststep)=
### QuestStep

One quest in a chain. Only quest_id and name are always known.

| Field | Type | Required |
| --- | --- | --- |
| `quest_id` | integer or null | no |
| `name` | string | yes |
| `level` | integer or null | no |
| `min_level` | integer or null | no |
| `giver` | string or null | no |
| `location` | string or null | no |
| `zone` | string or null | no |
| `dungeon` | string or null | no |
| `wowhead` | string or null | no |
| `known` | boolean | no |

(schema-reagent)=
### Reagent

| Field | Type | Required |
| --- | --- | --- |
| `item_id` | integer | yes |
| `name` | string | yes |
| `quantity` | integer | yes |
| `level` | integer or null | no |
| `level_source` | `corrected` \\| `shipped` \\| `item` or null | no |

(schema-recentview)=
### RecentView

| Field | Type | Required |
| --- | --- | --- |
| `destination` | string | yes |
| `kind` | string | yes |
| `created_at` | string | yes |
| `sent_at` | string or null | yes |
| `failed` | boolean | yes |
| `attempts` | integer | yes |
| `last_error` | string or null | yes |

(schema-reciperefresh)=
### RecipeRefresh

| Field | Type | Required |
| --- | --- | --- |
| `professions` | list of string | no |
| `recipes_listed` | integer | no |
| `recipes_fetched` | integer | no |
| `items_fetched` | integer | no |
| `items_not_found` | list of integer | no |
| `errors` | list of string | no |

(schema-recommendations)=
### Recommendations

| Field | Type | Required |
| --- | --- | --- |
| `level` | integer or null | yes |
| `window` | list of any or null | yes |
| `rows` | list of [SlotRecommendation](#schema-slotrecommendation) | yes |
| `dungeons` | list of [DungeonValue](#schema-dungeonvalue) | yes |
| `considered` | integer | yes |
| `unscored` | integer | yes |
| `attributions` | list of map of string | no |

(schema-refreshresult)=
### RefreshResult

| Field | Type | Required |
| --- | --- | --- |
| `found` | list of string | no |
| `missing` | list of string | no |
| `errors` | list of string | no |
| `icons` | integer | no |
| `companion_fetched` | integer | no |
| `companion_not_found` | list of integer | no |

(schema-rulesview)=
### RulesView

| Field | Type | Required |
| --- | --- | --- |
| `rules` | [UsageRules](#schema-usagerules) | yes |
| `defaults` | [UsageRules](#schema-usagerules) | yes |
| `customised` | boolean | yes |
| `weapon_type_options` | list of string | no |
| `armor_type_options` | list of string | no |
| `off_hand_type_options` | list of string | no |
| `two_hand_type_options` | list of string | no |

(schema-sendresult)=
### SendResult

| Field | Type | Required |
| --- | --- | --- |
| `ok` | boolean | yes |
| `status` | integer or null | no |
| `error` | string or null | no |
| `retry_after` | number or null | no |
| `gone` | boolean | no |

(schema-slotenchants)=
### SlotEnchants

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `item` | string or null | yes |
| `current` | [CurrentEnchant](#schema-currentenchant) or null | yes |
| `picks` | list of [EnchantPick](#schema-enchantpick) | yes |
| `current_is_weaker` | boolean | yes |

(schema-slotoutlook)=
### SlotOutlook

A slot whose targets are all above the character's level.

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `equipped` | [EquippedItem](#schema-equippeditem) or null | yes |
| `upcoming` | list of [UpcomingTarget](#schema-upcomingtarget) | yes |

(schema-slotrecommendation)=
### SlotRecommendation

| Field | Type | Required |
| --- | --- | --- |
| `slot` | string | yes |
| `equipped` | [EquippedItem](#schema-equippeditem) or null | yes |
| `candidates` | list of [Candidate](#schema-candidate) | yes |

(schema-spectree)=
### SpecTree

| Field | Type | Required |
| --- | --- | --- |
| `spec_id` | integer | yes |
| `name` | string | yes |
| `nodes` | list of [TalentNode](#schema-talentnode) | yes |

(schema-specialization)=
### Specialization

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `spent_points` | integer or null | no |
| `trees` | list of [TreePoints](#schema-treepoints) | no |
| `talents` | list of [Talent](#schema-talent) | no |

(schema-stats)=
### Stats

| Field | Type | Required |
| --- | --- | --- |
| `health` | integer or null | no |
| `strength` | integer or null | no |
| `agility` | integer or null | no |
| `stamina` | integer or null | no |
| `intellect` | integer or null | no |
| `spirit` | integer or null | no |
| `attack_power` | integer or null | no |
| `armor` | integer or null | no |
| `defense` | integer or null | no |
| `dodge` | number or null | no |
| `parry` | number or null | no |
| `block` | number or null | no |
| `crit` | number or null | no |

(schema-stepstatus)=
### StepStatus

| Field | Type | Required |
| --- | --- | --- |
| `talent` | string | yes |
| `talent_id` | integer or null | no |
| `rank` | integer | yes |
| `points` | integer | yes |
| `current` | integer | yes |
| `state` | `done` \\| `partial` \\| `pending` | yes |
| `first_point` | integer | yes |
| `level` | integer | yes |

(schema-syncstate)=
### SyncState

A character's queued sync, as the page polls it.

| Field | Type | Required |
| --- | --- | --- |
| `state` | `idle` \\| `queued` \\| `started` \\| `finished` \\| `failed` | yes |
| `result` | map of integer or null | no |
| `error` | string or null | no |

(schema-talent)=
### Talent

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `rank` | integer or null | no |
| `talent_id` | integer or null | no |
| `description` | string or null | no |
| `tree` | string or null | no |

(schema-talentnode)=
### TalentNode

| Field | Type | Required |
| --- | --- | --- |
| `node_id` | integer | yes |
| `talent_id` | integer | yes |
| `name` | string | yes |
| `spell_id` | integer or null | yes |
| `row` | integer | yes |
| `col` | integer | yes |
| `max_rank` | integer | yes |
| `ranks` | list of string | yes |
| `requires` | list of integer | yes |
| `icon_url` | string or null | no |

(schema-talentplan)=
### TalentPlan

| Field | Type | Required |
| --- | --- | --- |
| `spec` | string | yes |
| `steps` | list of [PlanStep](#schema-planstep) | no |

(schema-talentplanview)=
### TalentPlanView

| Field | Type | Required |
| --- | --- | --- |
| `plan` | [TalentPlan](#schema-talentplan) | yes |
| `spec` | string | yes |
| `current_spec` | string or null | yes |
| `level` | integer or null | yes |
| `available` | integer or null | yes |
| `spent` | integer or null | yes |
| `planned_points` | integer | yes |
| `steps` | list of [StepStatus](#schema-stepstatus) | yes |
| `next` | [NextPoint](#schema-nextpoint) or null | yes |
| `off_plan` | list of [OffPlan](#schema-offplan) | yes |
| `customised` | boolean | yes |

(schema-talentrefresh)=
### TalentRefresh

| Field | Type | Required |
| --- | --- | --- |
| `class_name` | string | yes |
| `trees` | integer | no |
| `icons` | integer | no |
| `errors` | list of string | no |

(schema-talenttreeview)=
### TalentTreeView

| Field | Type | Required |
| --- | --- | --- |
| `class_name` | string or null | yes |
| `tree` | [ClassTree](#schema-classtree) or null | yes |
| `loading` | boolean | yes |

(schema-targetinfo)=
### TargetInfo

What we know about a target item, merged from every source (ADR 0004). Precedence per field: manual (gear_targets.yaml) > Blizzard > Forever Companion.

| Field | Type | Required |
| --- | --- | --- |
| `sources` | list of `blizzard` \\| `companion` \\| `manual` | yes |
| `item_id` | integer or null | no |
| `item_level` | integer or null | no |
| `required_level` | integer or null | no |
| `quality` | string or null | no |
| `armor_type` | string or null | no |
| `armor` | integer or null | no |
| `stats` | list of [ItemStat](#schema-itemstat) | no |
| `dps` | number or null | no |
| `icon_url` | string or null | no |
| `drops` | list of string | no |
| `rewards` | list of string | no |
| `verified` | integer or null | no |
| `wowhead` | string or null | no |
| `conflicts` | list of string | no |

(schema-treepoints)=
### TreePoints

Points spent in one talent tree. Blizzard lists only trees with points in them.

| Field | Type | Required |
| --- | --- | --- |
| `name` | string | yes |
| `spent_points` | integer or null | no |

(schema-upcomingtarget)=
### UpcomingTarget

A target above the character's level: shown early so you can prepare for it.

| Field | Type | Required |
| --- | --- | --- |
| `target` | [GearTarget](#schema-geartarget) | yes |
| `target_info` | [TargetInfo](#schema-targetinfo) or null | yes |
| `level` | integer or null | yes |
| `score_delta` | number or null | no |

(schema-usagerules)=
### UsageRules

What the character can and wants to wear, and how many upgrades to list.

| Field | Type | Required |
| --- | --- | --- |
| `weapon_types` | list of string | yes |
| `armor_types` | list of string | yes |
| `plate_from_level` | integer or null | no |
| `mail_from_level` | integer or null | no |
| `two_handers` | boolean | no |
| `two_hand_types` | list of string or null | no |
| `off_hand_types` | list of string | no |
| `dual_wield_from_level` | integer or null | no |
| `levels_ahead` | integer | no |
| `per_slot` | integer | no |
| `min_gain` | number | no |

(schema-validationerror)=
### ValidationError

| Field | Type | Required |
| --- | --- | --- |
| `loc` | list of string or integer | yes |
| `msg` | string | yes |
| `type` | string | yes |
| `input` | any | no |
| `ctx` | object | no |

(schema-weightsupdate)=
### WeightsUpdate

| Field | Type | Required |
| --- | --- | --- |
| `weights` | map of number (minimum -10.0, maximum 10.0) | yes |

(schema-weightsview)=
### WeightsView

The active preset's weights, its defaults, and every preset to switch to.

| Field | Type | Required |
| --- | --- | --- |
| `weights` | map of number | yes |
| `defaults` | map of number | yes |
| `customised` | boolean | yes |
| `preset` | string | yes |
| `presets` | list of [PresetSummary](#schema-presetsummary) | yes |
