import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { enchantAdvice } from '../test/fixtures'
import { Enchants } from './Enchants'

describe('Enchants', () => {
  it('lists what to look for per slot, with short names, effects and gains', () => {
    render(<Enchants data={enchantAdvice} />)

    expect(screen.getByText('3 of 4 slots have a better enchant in reach', { exact: false })).toBeTruthy()
    expect(screen.getByText('Minor Deflect')).toBeTruthy()
    expect(screen.getByText('+3 Defense · Enchanting', { exact: false })).toBeTruthy()
    expect(screen.getByText('+3.0')).toBeTruthy()
    // Two picks above level 19 carry their estimated level.
    expect(screen.getAllByText('level 21')).toHaveLength(2)
  })

  it('shows the enchant on now and flags it when something better is in reach', () => {
    render(<Enchants data={enchantAdvice} />)

    expect(screen.getByText('✦ Stamina +3', { exact: false })).toBeTruthy()
    expect(screen.getByText('weaker than the best')).toBeTruthy()
  })

  it('flags recipes the character can make', () => {
    render(<Enchants data={enchantAdvice} />)

    expect(screen.getByText('Crude Scope')).toBeTruthy()
    expect(screen.getByText('you can make this')).toBeTruthy()
  })

  it('says why some slots and enchants have nothing listed', () => {
    render(<Enchants data={enchantAdvice} />)

    expect(screen.getByText('nothing to enchant')).toBeTruthy() // no necklace
    expect(screen.getByText(/16 in reach have no stat to weigh/)).toBeTruthy()
    expect(screen.getByText(/3 have no level estimate/)).toBeTruthy()
  })

  it('asks for an enchant data refresh before there is a catalog', () => {
    render(<Enchants data={{ ...enchantAdvice, recipes: 0, rows: [] }} />)

    expect(screen.getByText('No enchant data yet.', { exact: false })).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })
})
