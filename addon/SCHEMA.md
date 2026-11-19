# CharacterPlannerExport: data schema, version 1

The addon, in its own repository
([character-planner-export](https://github.com/thechainercygnus/character-planner-export),
ADR 0051), writes one table per character. The planner's parser (#183) reads it. ADR 0047
explains the choices; this file is the contract between them, and it stays in the planner.
Change it only by adding a version (see "Versions").

## Where it is

The `.toc` declares the table per character:

```
## SavedVariablesPerCharacter: CharacterPlannerExportDB
```

The client writes it to
`_forever_\WTF\Account\<ACCOUNT>\91\<Character>\SavedVariables\CharacterPlannerExport.lua`
on logout, `/reload` or client exit, and at no other time.

## Shape

```lua
CharacterPlannerExportDB = {
	["schemaVersion"] = 1,
	["addonVersion"] = "0.1.0",
	["capturedAt"] = 1794700000,
	["character"] = {
		["name"] = "Brumboldt",
		["surname"] = "Doomlet",
		["level"] = 24,
		["region"] = "US",
		["realm"] = "91",
	},
	["bags"] = {
		["capturedAt"] = 1794699950,
		["items"] = {
			{
				["container"] = 0,
				["slot"] = 1,
				["itemId"] = 6948,
				["count"] = 1,
				["quality"] = 1,
			},
		},
	},
	["bank"] = {
		["capturedAt"] = 1794600000,
		["items"] = {
		},
	},
	["quests"] = {
		["capturedAt"] = 1794699990,
		["log"] = {
			{
				["questId"] = 1640,
				["title"] = "The Summoning",
				["complete"] = false,
				["objectives"] = {
					{
						["text"] = "Summon and defeat Bartleby",
						["type"] = "monster",
						["done"] = 0,
						["needed"] = 1,
						["finished"] = false,
					},
				},
			},
		},
		["completed"] = {
			1638,
			1639,
		},
	},
}
```

The values are made up. The layout follows how the client writes SavedVariables (tabs,
`["key"] = value`, a trailing comma), but the parser doesn't depend on layout: any valid
version of the subset in "What the parser accepts" works.

## Fields

Times are Unix seconds, UTC, from `GetServerTime()`. Keys are camelCase, as is usual in
Lua; the planner maps them to its own names.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schemaVersion` | integer | yes | This document's version: 1. |
| `addonVersion` | string | yes | The addon's own version, from its `.toc`. For diagnostics only. |
| `capturedAt` | integer | yes | When the table was last written: the newest of the sections' times. |
| `character.name` | string | yes | `UnitName("player")`. |
| `character.surname` | string | no | The character's Forever surname, if the addon can read it (#179 finds out how). |
| `character.level` | integer | yes | `UnitLevel("player")`. |
| `character.region` | string | no | `"US"`, `"EU"`, `"KR"` or `"TW"`, if the client says (verify `GetCurrentRegionName()` on Forever). |
| `character.realm` | string | no | `GetRealmName()`, for diagnostics. On Forever it's the server's name (`"CAMWOW US2 Realm 7 PvE"` in the first real file), not the WTF folder's `91`. |
| `bags` | table | no | Absent until the bags are first recorded. |
| `bags.capturedAt` | integer | yes | When the bags were recorded. |
| `bags.items` | list | yes | One entry per occupied slot; empty slots are left out. |
| `bank` | table | no | **Absent** until the bank has been opened: "not seen yet". Present with no items: an empty bank. |
| `bank.capturedAt` | integer | yes | When the bank was last open. Often days older than the bags. |
| `bank.items` | list | yes | As `bags.items`, with the bank's own `container` numbers. |
| `quests` | table | no | Absent until the quest log is first recorded. |
| `quests.capturedAt` | integer | yes | When the log was recorded. |
| `quests.log` | list | yes | The quests in the log, zone headers left out. |
| `quests.completed` | list | no | Quest ids the game reports completed, for the quests the addon checks (#182's stretch). |

An item entry:

| Field | Type | Meaning |
|---|---|---|
| `container` | integer | The bag or bank container index (`Enum.BagIndex` on modern clients). |
| `slot` | integer | The slot within it, from 1. |
| `itemId` | integer | The item's id. Names, icons and stats come from the planner's catalog, not the file. |
| `count` | integer | The stack size, 1 or more. |
| `quality` | integer | `Enum.ItemQuality`: 0 poor, 1 common, 2 uncommon, 3 rare, 4 epic, 5 legendary. |

A quest entry:

| Field | Type | Meaning |
|---|---|---|
| `questId` | integer | The quest's id. |
| `title` | string | Its title, as the client shows it. |
| `complete` | boolean | Ready to hand in. |
| `objectives` | list | Its objectives, in the client's order. |

An objective: `text` (string), `type` (string, as the client reports it, such as
`"monster"`, `"item"` or `"object"`), `done` and `needed` (integers), `finished`
(boolean).

Unknown keys are ignored, so the addon can add fields for its own use without a new
version. Missing required fields, or values of the wrong type, reject the whole file.

## What the parser accepts

Only what SavedVariables files contain:
- top-level assignments, `Name = value`, one or more (other names are ignored);
- tables: `{ }` with `["key"] = value`, `[1] = value`, `key = value` and plain list
  entries, separated by `,` or `;`, a trailing separator allowed;
- strings in `"` or `'`, with Lua's escapes (`\n`, `\"`, `\\`, `\ddd` and the rest);
- numbers: decimal, hexadecimal and exponents; no `inf` or `nan`;
- `true`, `false` and `nil`;
- `--` and `--[[ ]]` comments; a UTF-8 byte-order mark; CRLF line endings.

Anything else (function calls, operators, `function`, a name used as a value, string
concatenation) is an error naming the line and column. Nothing in the file is ever run.

Limits (ADR 0047): the file at most 1 MiB, nesting at most 16 deep, at most 50,000
values, strings at most 4 KiB.

## Versions

- **1** (this document).

A change that a version-1 parser would read wrongly (a renamed, removed or retyped field)
needs version 2: the addon writes `schemaVersion = 2`, this document gains a section, and
the parser learns it before the addon ships it. The parser refuses versions it doesn't
know, with a message saying to update the planner.
