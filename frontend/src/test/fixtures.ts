import type { Candidate, EnchantAdvice, EnchantOption, PoolItem, PoolSource, Recommendations } from '../api'

export const hallDrop: PoolSource = {
  kind: 'drop',
  dungeon_id: 'hall-of-thanes',
  dungeon: 'Hall of Thanes',
  min_level: 13,
  max_level: 18,
  detail: 'Plunder',
  choice: false,
  quest_min_level: null,
  quest: null,
  chain: [],
}

export const deadminesQuest: PoolSource = {
  kind: 'quest',
  dungeon_id: 'the-deadmines',
  dungeon: 'The Deadmines',
  min_level: 17,
  max_level: 26,
  detail: 'The Defias Brotherhood',
  choice: true,
  quest_min_level: 20,
  quest: null,
  chain: [],
}

export function poolItem(overrides: Partial<PoolItem>): PoolItem {
  return {
    item_id: 1,
    name: 'Item',
    slot: 'waist',
    quality: 'RARE',
    sources: [hallDrop],
    item_slot: 'Waist',
    weapon_type: null,
    item_level: 18,
    required_level: 13,
    effective_level: 13,
    armor_type: 'Mail',
    armor: 100,
    stats: { Stamina: 7 },
    dps: null,
    icon_url: null,
    wowhead: 'https://www.wowhead.com/forever/item=1',
    ...overrides,
  }
}

export function candidate(item: PoolItem, gain: number, overrides: Partial<Candidate> = {}): Candidate {
  return {
    item,
    score_gain: gain,
    item_level_delta: 4,
    armor_delta: 27,
    stat_deltas: { Stamina: 7 },
    usable_now: true,
    is_target: false,
    pinned: false,
    ...overrides,
  }
}

export const girdle = poolItem({ item_id: 270230, name: 'Kindlegem Girdle' })
export const laterBelt = poolItem({
  item_id: 2,
  name: 'Later Belt',
  required_level: null,
  effective_level: 20,
  sources: [deadminesQuest],
})

export const recommendations: Recommendations = {
  level: 18,
  window: [15, 28],
  rows: [
    {
      slot: 'WAIST',
      equipped: null,
      candidates: [candidate(girdle, 9.7, { is_target: true }), candidate(laterBelt, 3.2, { usable_now: false })],
    },
    { slot: 'NECK', equipped: null, candidates: [] },
    { slot: 'TRINKET_2', equipped: null, candidates: [] },
  ],
  dungeons: [
    {
      dungeon_id: 'hall-of-thanes',
      dungeon: 'Hall of Thanes',
      min_level: 13,
      max_level: 18,
      total_gain: 9.7,
      upgrades: [{ slot: 'WAIST', item: girdle, score_gain: 9.7, source: hallDrop }],
    },
    {
      dungeon_id: 'the-deadmines',
      dungeon: 'The Deadmines',
      min_level: 17,
      max_level: 26,
      total_gain: 3.2,
      upgrades: [{ slot: 'WAIST', item: laterBelt, score_gain: 3.2, source: deadminesQuest }],
    },
  ],
  considered: 2,
  unscored: 5,
  attributions: [],
}

function enchantOption(overrides: Partial<EnchantOption> & Pick<EnchantOption, 'recipe_id' | 'name'>): EnchantOption {
  return {
    profession: 'Enchanting',
    category: 'Bracer Enchants',
    slots: ['WRIST'],
    two_handed: false,
    shield_only: false,
    text: null,
    effects: {},
    effects_source: 'description',
    temporary: false,
    crafted_item_id: null,
    season_of_discovery: false,
    estimated_level: 1,
    ...overrides,
  }
}

/** Shaped like GET /api/enchants/recommendations for the 2026-11-11 gear. */
export const enchantAdvice: EnchantAdvice = {
  level: 19,
  recipes: 204,
  considered: 35,
  unscored: 16,
  unknown_level: 3,
  rows: [
    {
      slot: 'WRIST',
      item: 'Cryptwalker Bracers',
      current: null,
      current_is_weaker: false,
      picks: [
        {
          option: enchantOption({
            recipe_id: 7510,
            name: 'Enchant Bracer - Stamina',
            effects: { Stamina: 5 },
            estimated_level: 21,
          }),
          score: 5,
          score_gain: 5,
          usable_now: false,
          can_make: false,
        },
        {
          option: enchantOption({
            recipe_id: 4293,
            name: 'Enchant Bracer - Minor Deflect',
            text: 'Permanently enchant bracers so the defense skill of the wearer is increased by 3.',
            effects: { Defense: 3 },
          }),
          score: 3,
          score_gain: 3,
          usable_now: true,
          can_make: false,
        },
      ],
    },
    {
      slot: 'FEET',
      item: "Greaves of the People's Militia",
      current: { text: 'Enchanted: Stamina +3', effects: { Stamina: 3 }, score: 3 },
      current_is_weaker: true,
      picks: [
        {
          option: enchantOption({
            recipe_id: 7508,
            name: 'Enchant Boots - Lesser Stamina',
            category: 'Boots Enchants',
            slots: ['FEET'],
            effects: { Stamina: 4 },
            estimated_level: 21,
          }),
          score: 4,
          score_gain: 1,
          usable_now: false,
          can_make: false,
        },
      ],
    },
    {
      slot: 'RANGED',
      item: 'Calibrated Blunderbuss',
      current: null,
      current_is_weaker: false,
      picks: [
        {
          option: enchantOption({
            recipe_id: 2421,
            name: 'Crude Scope',
            profession: 'Engineering',
            category: 'Scopes',
            slots: ['RANGED'],
            effects: { 'Weapon Damage': 1 },
            effects_source: 'curated',
            crafted_item_id: 4405,
            estimated_level: null,
          }),
          score: 0.09,
          score_gain: 0.09,
          usable_now: true,
          can_make: true,
        },
      ],
    },
    { slot: 'NECK', item: null, current: null, current_is_weaker: false, picks: [] },
  ],
}
