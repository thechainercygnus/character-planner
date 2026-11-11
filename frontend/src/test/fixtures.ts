import type { Candidate, PoolItem, PoolSource, Recommendations } from '../api'

export const hallDrop: PoolSource = {
  kind: 'drop',
  dungeon_id: 'hall-of-thanes',
  dungeon: 'Hall of Thanes',
  min_level: 13,
  max_level: 18,
  detail: 'Plunder',
  choice: false,
  quest_min_level: null,
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
