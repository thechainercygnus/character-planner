import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Candidate, PoolItem, Recommendations as RecommendationsData } from '../api'
import { Recommendations } from './Recommendations'

function poolItem(overrides: Partial<PoolItem>): PoolItem {
  return {
    item_id: 1,
    name: 'Item',
    slot: 'waist',
    quality: 'RARE',
    sources: [
      {
        kind: 'drop',
        dungeon_id: 'hall-of-thanes',
        dungeon: 'Hall of Thanes',
        min_level: 13,
        max_level: 18,
        detail: 'Plunder',
        choice: false,
        quest_min_level: null,
      },
    ],
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

function candidate(item: PoolItem, gain: number, overrides: Partial<Candidate> = {}): Candidate {
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

const girdle = poolItem({ item_id: 270230, name: 'Kindlegem Girdle' })
const later = poolItem({
  item_id: 2,
  name: 'Later Belt',
  required_level: null,
  effective_level: 20,
  sources: [
    {
      kind: 'quest',
      dungeon_id: 'the-deadmines',
      dungeon: 'The Deadmines',
      min_level: 17,
      max_level: 26,
      detail: 'The Defias Brotherhood',
      choice: true,
      quest_min_level: 20,
    },
  ],
})

const data: RecommendationsData = {
  level: 18,
  window: [15, 28],
  rows: [
    {
      slot: 'WAIST',
      equipped: null,
      candidates: [candidate(girdle, 9.7, { is_target: true }), candidate(later, 3.2, { usable_now: false })],
    },
    { slot: 'NECK', equipped: null, candidates: [] },
  ],
  dungeons: [
    {
      dungeon_id: 'hall-of-thanes',
      dungeon: 'Hall of Thanes',
      min_level: 13,
      max_level: 18,
      total_gain: 9.7,
      upgrades: ['Kindlegem Girdle (+9.7)'],
    },
  ],
  considered: 2,
  unscored: 5,
  attributions: [],
}

describe('Recommendations', () => {
  it('shows the best upgrade per slot with its gain, source and tags', () => {
    render(<Recommendations data={data} />)

    expect(screen.getByText('1 of 2 slots have an upgrade in reach', { exact: false })).toBeTruthy()
    expect(screen.getByText('(5 more without stats yet)', { exact: false })).toBeTruthy()
    expect(screen.getByText('Kindlegem Girdle').closest('a')?.getAttribute('href')).toContain('item=1')
    expect(screen.getByText('your target')).toBeTruthy()
    expect(screen.getAllByText('+9.7 score').length).toBe(2) // the row and the dungeon list
    expect(screen.getByText('Hall of Thanes – Plunder')).toBeTruthy()
    expect(screen.getByText('nothing better in reach')).toBeTruthy()
  })

  it('lists other options with quest sources and level tags', () => {
    render(<Recommendations data={data} />)

    expect(screen.getByText('1 more option')).toBeTruthy()
    expect(screen.getByText('Quest: The Defias Brotherhood (The Deadmines), choice')).toBeTruthy()
    expect(screen.getByText('level 20')).toBeTruthy()
  })

  it('ranks dungeons worth running', () => {
    render(<Recommendations data={data} />)

    expect(screen.getByText('Dungeons worth running')).toBeTruthy()
    expect(screen.getByText('Hall of Thanes (13–18)')).toBeTruthy()
  })

  it('explains how to build the pool when it is empty', () => {
    render(<Recommendations data={{ ...data, rows: [], dungeons: [], considered: 0, unscored: 0 }} />)

    expect(screen.getByText('No item pool yet.', { exact: false })).toBeTruthy()
  })
})
