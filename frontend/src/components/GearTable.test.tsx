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
    source: 'api',
    item_id: 6187,
    item_level: 17,
    required_level: 0,
    quality: 'UNCOMMON',
    armor_type: 'Shield',
    armor: null,
    stats: [],
    icon_url: null,
  },
  reached: false,
  verdict: 'downgrade',
  item_level_delta: -4,
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
  warning: null,
}

const manualUpgrade: GearRow = {
  ...unknown,
  slot: 'LEGS',
  target: target('LEGS', 'Direhammer Leggings'),
  target_info: { ...downgrade.target_info!, source: 'manual', item_level: 22, armor_type: 'Leather' },
  verdict: 'upgrade',
  item_level_delta: 9,
  warning: 'Leather replacing Mail',
}

const plan: GearPlan = {
  level: 18,
  bracket_min_level: 15,
  next_bracket_level: 20,
  next_bracket_size: 15,
  rows: [downgrade, unknown, manualUpgrade],
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
    expect(screen.getByText('ilvl 22 · Leather · manual data')).toBeTruthy()
    expect(screen.getByText('not in Battle.net item data')).toBeTruthy()
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
