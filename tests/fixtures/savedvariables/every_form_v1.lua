-- Every form the reader accepts, in one valid version-1 file. Made up, not from a game.
--[[ A long comment,
     over two lines. ]]
--[==[ A long comment with a level: ]] doesn't end it. ]==]
OtherAddonSetting = 'kept but ignored';
CharacterPlannerExportDB = {
	schemaVersion = 1, -- a bare name as a key
	["addonVersion"] = "0.1.0-dev";
	["capturedAt"] = 0x6AFA3BE0,
	character = {
		name = 'Brumboldt',
		surname = "Doom\108et",
		level = 24,
		region = "US",
		realm = "\x39\u{31}",
	},
	["bags"] = {
		capturedAt = 1794699950,
		items = {
			{ container = 0, slot = 1, itemId = 6948, count = 1, quality = 1 },
			[3] = { container = 0, slot = 2, itemId = 2589, count = 20, quality = 1 },
			{ container = -1, slot = 3, itemId = 4306, count = 5, quality = 1, };
		},
	},
	["quests"] = {
		["capturedAt"] = 1794699990,
		log = {
			{
				questId = 1640,
				title = "Quote \"inside\", tab\tand a back\\slash",
				complete = false,
				objectives = {},
				addonOnlyNote = nil,
			},
		},
		completed = {},
	},
	["somethingNewer"] = { true, false },
}
