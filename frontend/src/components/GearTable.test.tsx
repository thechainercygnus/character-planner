import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { GearPlan } from '../api'
import { GearTable } from './GearTable'

const plan: GearPlan = {
  level: 18,
  bracket_min_level: 15,
  next_bracket_level: 20,
  next_bracket_size: 15,
  rows: [
    {
      slot: 'OFF_HAND',
      equipped: {
        slot: 'OFF_HAND',
        name: 'Burnished Shield',
        item_id: 3655,
        quality: 'UNCOMMON',
        quality_name: 'Uncommon',
        item_level: 21,
        armor: 428,
        stats: [
          { name: 'Strength', value: 2 },
          { name: 'Stamina', value: 3 },
        ],
      },
      target: { slot: 'OFF_HAND', item: 'Dwarven Defender', source: 'Quest', priority: 1 },
      reached: false,
    },
    {
      slot: 'BACK',
      equipped: null,
      target: { slot: 'BACK', item: 'Spiritwraith Drape', source: 'Hall of Thanes', priority: 10 },
      reached: false,
    },
  ],
}

describe('GearTable', () => {
  it('shows equipped items against their targets', () => {
    render(<GearTable plan={plan} />)

    expect(screen.getByText('Off Hand')).toBeTruthy()
    expect(screen.getByText('Burnished Shield').className).toContain('quality-uncommon')
    expect(screen.getByText('428 armor, +2 Strength, +3 Stamina')).toBeTruthy()
    expect(screen.getByText('Dwarven Defender')).toBeTruthy()
    expect(screen.getByText('empty')).toBeTruthy()
    expect(screen.getByText(/2 of 2 still to get/)).toBeTruthy()
    expect(screen.getByText(/Next bracket at level 20/)).toBeTruthy()
  })

  it('marks reached targets', () => {
    const done: GearPlan = {
      ...plan,
      rows: [{ ...plan.rows[0], reached: true }],
    }
    render(<GearTable plan={done} />)

    expect(screen.getByText(/Every target reached/)).toBeTruthy()
    expect(screen.getByText(/✓/).textContent).toContain('Dwarven Defender')
  })

  it('handles levels with no bracket', () => {
    render(<GearTable plan={{ ...plan, bracket_min_level: null, rows: [] }} />)
    expect(screen.getByText(/No gear targets for this level/)).toBeTruthy()
  })
})
