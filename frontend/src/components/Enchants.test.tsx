import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EnchantAdvice } from '../api'
import { enchantAdvice } from '../test/fixtures'
import { Enchants } from './Enchants'

function renderEnchants(data: EnchantAdvice = enchantAdvice) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Enchants data={data} />
    </QueryClientProvider>,
  )
}

describe('Enchants', () => {
  it('links worn items and crafted enchants to Wowhead, but not plain enchants (#225)', () => {
    const scope = 'https://www.wowhead.com/forever/item=4405'
    const data = structuredClone(enchantAdvice)
    const row = data.rows[0]
    row.wowhead = 'https://www.wowhead.com/forever/item=6542'
    row.picks[0].option.crafted_item_id = 4405
    row.picks[0].option.wowhead = scope
    renderEnchants(data)

    expect(screen.getByRole('link', { name: row.item! }).getAttribute('href')).toBe(row.wowhead)
    expect(screen.getByRole('link', { name: 'Stamina' }).getAttribute('href')).toBe(scope)
    // A plain enchant has no item, and no spell id is known: plain text.
    const plain = row.picks[1].option.name.replace(/^Enchant [^-]+ - /, '')
    expect(screen.getByText(plain)).toBeTruthy()
    expect(screen.queryByRole('link', { name: plain })).toBeNull()
  })

  it('lists what to look for per slot, with short names, effects and gains', () => {
    renderEnchants()

    expect(screen.getByText('3 of 4 slots have a better enchant in reach', { exact: false })).toBeTruthy()
    expect(screen.getByText('Minor Deflect')).toBeTruthy()
    expect(screen.getByText('+3 Defense · Enchanting', { exact: false })).toBeTruthy()
    expect(screen.getByText('+3.0')).toBeTruthy()
    // Two picks above level 19 carry their estimated level.
    expect(screen.getAllByText('level 21')).toHaveLength(2)
  })

  it('shows the enchant on now and flags it when something better is in reach', () => {
    renderEnchants()

    expect(screen.getByText('✦ Stamina +3', { exact: false })).toBeTruthy()
    expect(screen.getByText('weaker than the best')).toBeTruthy()
  })

  it('flags recipes the character can make', () => {
    renderEnchants()

    expect(screen.getByText('Crude Scope')).toBeTruthy()
    expect(screen.getByText('you can make this')).toBeTruthy()
  })

  it('says why some slots and enchants have nothing listed', () => {
    renderEnchants()

    expect(screen.getByText('nothing to enchant')).toBeTruthy() // no necklace
    expect(screen.getByText(/16 in reach have no stat to weigh/)).toBeTruthy()
    expect(screen.getByText(/3 have no level estimate/)).toBeTruthy()
  })

  it('asks for an enchant data refresh before there is a catalog', () => {
    renderEnchants({ ...enchantAdvice, recipes: 0, rows: [] })

    expect(screen.getByText('No enchant data yet.', { exact: false })).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })
})
