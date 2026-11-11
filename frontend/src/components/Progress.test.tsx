import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Progress as ProgressData, ProgressPoint } from '../api'
import { Progress } from './Progress'

function point(captured_at: string, overrides: Partial<ProgressPoint>): ProgressPoint {
  return {
    captured_at,
    level: 18,
    item_level: 14.6,
    gear_score: 120.4,
    health: 538,
    armor: 1105,
    stamina: 55,
    ...overrides,
  }
}

const data: ProgressData = {
  points: [
    point('2026-11-11T19:00:07', {}),
    point('2026-11-12T03:00:00', { level: 19, item_level: 14.9, gear_score: 123.1, health: 600 }),
  ],
  gear_changes: [
    {
      captured_at: '2026-11-12T03:00:00',
      slot: 'WAIST',
      before: "Belt of the People's Militia",
      after: 'Kindlegem Girdle',
      item_level_before: 14,
      item_level_after: 18,
      score_change: 2.7,
    },
  ],
  level_ups: [{ captured_at: '2026-11-12T03:00:00', level: 19 }],
}

describe('Progress', () => {
  it('shows current values with their change since the first sync', () => {
    render(<Progress data={data} />)

    expect(screen.getByText('2 syncs since', { exact: false })).toBeTruthy()
    expect(screen.getByText('+62', { exact: false }).textContent).toContain('since') // health 538 -> 600
    expect(screen.getAllByText('no change', { exact: false }).length).toBe(2) // armor, stamina
    expect(screen.getAllByRole('img').map((chart) => chart.getAttribute('aria-label'))).toEqual([
      'Level over time',
      'Item level over time',
      'Gear score over time',
      'Health over time',
      'Armor over time',
      'Stamina over time',
    ])
  })

  it('logs gear swaps and level-ups', () => {
    render(<Progress data={data} />)

    expect(screen.getByText("Waist: Belt of the People's Militia → Kindlegem Girdle")).toBeTruthy()
    expect(screen.getByText('+2.7')).toBeTruthy()
    expect(screen.getByText('Reached level 19')).toBeTruthy()
  })

  it('shows the hovered value in the chart caption', () => {
    const { container } = render(<Progress data={data} />)
    const healthChart = screen.getByRole('img', { name: 'Health over time' }).closest('figure')!
    expect(healthChart.querySelector('figcaption strong')?.textContent).toBe('600')

    fireEvent.mouseEnter(healthChart.querySelectorAll('rect.hit')[0])
    expect(healthChart.querySelector('figcaption strong')?.textContent).toBe('538')
    expect(container.querySelectorAll('.marker.active').length).toBe(1)
  })

  it('asks for a sync when there is no history', () => {
    render(<Progress data={{ points: [], gear_changes: [], level_ups: [] }} />)
    expect(screen.getByText('No syncs yet. Every sync adds a point here.')).toBeTruthy()
  })
})
