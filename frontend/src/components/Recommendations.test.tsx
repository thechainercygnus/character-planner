import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { recommendations } from '../test/fixtures'
import { Recommendations } from './Recommendations'

describe('Recommendations', () => {
  it('shows one compact row per slot with an upgrade', () => {
    render(<Recommendations data={recommendations} />)

    expect(screen.getByText('1 of 3 slots have an upgrade in reach', { exact: false })).toBeTruthy()
    expect(screen.getByText('(5 more without stats yet)', { exact: false })).toBeTruthy()
    expect(screen.getByText('Kindlegem Girdle').closest('a')?.getAttribute('href')).toContain('item=1')
    expect(screen.getByText('your target')).toBeTruthy()
    expect(screen.getByText('+9.7')).toBeTruthy()
    // Details stay hidden until the row is opened.
    expect(screen.queryByText('Hall of Thanes – Plunder')).toBeNull()
    expect(screen.queryByText('Later Belt')).toBeNull()
  })

  it('lists slots without upgrades on one line', () => {
    render(<Recommendations data={recommendations} />)

    expect(screen.getByText('No upgrades in reach: Neck, Trinket 2')).toBeTruthy()
  })

  it('opens a row to show sources, changes and other options', () => {
    render(<Recommendations data={recommendations} />)

    fireEvent.click(screen.getByRole('button', { name: 'Show details for Waist' }))

    expect(screen.getByText('Hall of Thanes – Plunder')).toBeTruthy()
    expect(screen.getByText('+4 item level · +27 armor · +7 Stamina')).toBeTruthy()
    expect(screen.getByText('Later Belt')).toBeTruthy()
    expect(screen.getByText('Quest: The Defias Brotherhood (The Deadmines), choice')).toBeTruthy()
    expect(screen.getByText('level 20')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Hide details for Waist' }))
    expect(screen.queryByText('Later Belt')).toBeNull()
  })

  it('explains how to build the pool when it is empty', () => {
    render(<Recommendations data={{ ...recommendations, rows: [], dungeons: [], considered: 0, unscored: 0 }} />)

    expect(screen.getByText('No item pool yet.', { exact: false })).toBeTruthy()
  })
})
