import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EquippedItem, GearPlan, GearRow, GearTarget } from '../api'
import { GearTable } from './GearTable'

const shield: EquippedItem = {
  slot: 'OFF_HAND',
  name: 'Burnished Shield',
  item_id: 3655,
  quality: 'UNCOMMON',
  quality_name: 'Uncommon',
  item_level: 21,
  armor_type: 'Shield',
  armor: 428,
  stats: [
    { name: 'Strength', value: 2 },
    { name: 'Stamina', value: 3 },
  ],
  dps: null,
  icon_url: 'https://render.worldofwarcraft.com/forever-us/icons/56/134949.jpg',
}

function target(slot: string, item: string): GearTarget {
  return {
    slot,
    item,
    source: 'Hall of Thanes',
    priority: null,
    item_id: null,
    item_level: null,
    armor_type: null,
    armor: null,
    stats: {},
  }
}

const downgrade: GearRow = {
  slot: 'OFF_HAND',
  equipped: shield,
  target: target('OFF_HAND', 'Dwarven Defender'),
  target_info: {
    sources: ['blizzard'],
    item_id: 6187,
    item_level: 17,
    required_level: 0,
    quality: 'UNCOMMON',
    armor_type: 'Shield',
    armor: null,
    stats: [],
    dps: null,
    icon_url: null,
    drops: [],
    rewards: [],
    verified: null,
    wowhead: null,
    conflicts: [],
  },
  reached: false,
  verdict: 'downgrade',
  item_level_delta: -4,
  armor_delta: null,
  stat_deltas: {},
  score_delta: null,
  verdict_basis: 'item_level',
  warning: null,
}

const unknown: GearRow = {
  slot: 'WAIST',
  equipped: null,
  target: target('WAIST', 'Kindlegem Girdle'),
  target_info: null,
  reached: false,
  verdict: 'unknown',
  item_level_delta: null,
  armor_delta: null,
  stat_deltas: {},
  score_delta: null,
  verdict_basis: 'item_level',
  warning: null,
}

const manualUpgrade: GearRow = {
  ...unknown,
  slot: 'LEGS',
  target: target('LEGS', 'Direhammer Leggings'),
  target_info: { ...downgrade.target_info!, sources: ['manual'], item_level: 22, armor_type: 'Leather' },
  verdict: 'upgrade',
  item_level_delta: 9,
  warning: 'Leather replacing Mail',
}

const companionUpgrade: GearRow = {
  ...unknown,
  slot: 'WAIST',
  target: target('WAIST', 'Kindlegem Girdle'),
  target_info: {
    ...downgrade.target_info!,
    sources: ['companion'],
    item_id: 270230,
    item_level: 18,
    quality: 'RARE',
    armor_type: 'Mail',
    armor: 100,
    stats: [{ name: 'Stamina', value: 7 }],
    drops: ['Hall of Thanes - Magmatus'],
    verified: 3,
    wowhead: 'https://www.wowhead.com/forever/item=270230',
    conflicts: ['item level: Blizzard 17, Forever Companion 18'],
  },
  verdict: 'upgrade',
  item_level_delta: 4,
  armor_delta: 27,
  stat_deltas: { Stamina: 7 },
  score_delta: 9.7,
  verdict_basis: 'score',
}

const plan: GearPlan = {
  level: 18,
  bracket_min_level: 15,
  next_bracket_level: 20,
  next_bracket_size: 15,
  rows: [downgrade, unknown, manualUpgrade],
  attributions: [],
}

describe('GearTable', () => {
  it('shows equipped items with their details and icon', () => {
    const { container } = render(<GearTable plan={plan} />)

    expect(screen.getByText('Off Hand')).toBeTruthy()
    expect(screen.getByText('Burnished Shield').className).toContain('quality-uncommon')
    expect(screen.getByText('ilvl 21 · Shield · 428 armor · +2 Strength · +3 Stamina')).toBeTruthy()
    expect(container.querySelector(`img[src="${shield.icon_url}"]`)).not.toBeNull()
  })

  it('labels each verdict with its item level change', () => {
    render(<GearTable plan={plan} />)

    expect(screen.getByText(/already better/).textContent).toBe('already better (-4 ilvl)')
    expect(screen.getByText(/^upgrade/).textContent).toBe('upgrade (+9 ilvl)')
    expect(screen.getByText('unknown')).toBeTruthy()
    expect(screen.getByText('Leather replacing Mail')).toBeTruthy()
  })

  it('says where target data came from', () => {
    render(<GearTable plan={plan} />)

    expect(screen.getByText('ilvl 17 · Shield')).toBeTruthy()
    expect(screen.getByText('from Blizzard')).toBeTruthy()
    expect(screen.getByText('from manual')).toBeTruthy()
    expect(screen.getByText('no item data yet')).toBeTruthy()
  })

  it('shows Forever Companion data: gains, drops, link, conflicts and credit', () => {
    const credit = { name: 'Forever Companion', url: 'https://forevercompanion.io', text: 'Item data from Forever Companion.' }
    render(<GearTable plan={{ ...plan, rows: [companionUpgrade], attributions: [credit] }} />)

    expect(screen.getByText('+27 armor · +7 Stamina')).toBeTruthy()
    expect(screen.getByText(/^upgrade/).textContent).toBe('upgrade (+9.7 score)')
    expect(screen.getByText('+4 item level')).toBeTruthy()
    expect(screen.getByText('Hall of Thanes - Magmatus')).toBeTruthy()
    expect(screen.getByText('from Forever Companion (3 verified)')).toBeTruthy()
    expect(screen.getByText('Kindlegem Girdle').getAttribute('href')).toBe(companionUpgrade.target_info!.wowhead)
    expect(screen.getByText(/Sources disagree on item level/)).toBeTruthy()
    expect(screen.getByText('Forever Companion').getAttribute('href')).toBe('https://forevercompanion.io')
  })

  it('summarises upgrades and gaps', () => {
    render(<GearTable plan={plan} />)
    expect(screen.getByText(/1 upgrade to chase, 1 without item data\./)).toBeTruthy()
    expect(screen.getByText(/Next bracket at level 20/)).toBeTruthy()
  })

  it('handles levels with no bracket', () => {
    render(<GearTable plan={{ ...plan, bracket_min_level: null, rows: [] }} />)
    expect(screen.getByText(/No gear targets for this level/)).toBeTruthy()
  })
})
