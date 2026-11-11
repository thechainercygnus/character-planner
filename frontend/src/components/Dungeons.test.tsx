import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { recommendations } from '../test/fixtures'
import { Dungeons } from './Dungeons'

describe('Dungeons', () => {
  it('shows a card per dungeon with its upgrades, slots and sources', () => {
    render(<Dungeons data={recommendations} />)

    const titles = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(titles).toEqual(['1. Hall of Thanes · levels 13–18', '2. The Deadmines · levels 17–26'])
    expect(screen.getByText('Kindlegem Girdle')).toBeTruthy()
    expect(screen.getByText('Plunder')).toBeTruthy()
    expect(screen.getByText('Quest: The Defias Brotherhood')).toBeTruthy()
    expect(screen.getAllByText('+9.7').length).toBe(2) // card total and the item
  })

  it('says so when nothing is worth running', () => {
    render(<Dungeons data={{ ...recommendations, dungeons: [] }} />)

    expect(screen.getByText('No dungeon in reach holds an upgrade you can wear yet.')).toBeTruthy()
  })
})
