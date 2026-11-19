import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ProfessionBook, ProfessionsView, RecipeBook } from '../api'
import { Professions } from './Professions'

const SEARCH = 'https://www.wowhead.com/forever/search?q='

// Shaped as the server's recipe book for the real snapshot: Engineering's tier cached,
// with one recipe looked up (Standard Scope, which makes item 4406); Mining's not yet.
const engineering: ProfessionBook = {
  name: 'Engineering',
  primary: true,
  skill: 104,
  max_skill: 150,
  listed: true,
  known: 1,
  unlearned: 2,
  season_of_discovery: 1,
  categories: [
    {
      name: 'Scopes',
      season_of_discovery: false,
      recipes: [
        {
          recipe_id: 2421,
          name: 'Crude Scope',
          known: true,
          crafted_item_id: null,
          wowhead: `${SEARCH}Crude+Scope`,
        },
        {
          recipe_id: 2435,
          name: 'Standard Scope',
          known: false,
          crafted_item_id: 4406,
          wowhead: 'https://www.wowhead.com/forever/item=4406',
        },
        {
          recipe_id: 2459,
          name: 'Accurate Scope',
          known: false,
          crafted_item_id: null,
          wowhead: `${SEARCH}Accurate+Scope`,
        },
      ],
    },
    {
      name: 'SEASON OF DISCOVERY',
      season_of_discovery: true,
      recipes: [
        {
          recipe_id: 49656,
          name: 'Soul Vessel',
          known: false,
          crafted_item_id: 211427,
          wowhead: 'https://www.wowhead.com/forever/item=211427',
        },
      ],
    },
  ],
}
const mining: ProfessionBook = {
  ...engineering,
  name: 'Mining',
  listed: false,
  known: 1,
  unlearned: 0,
  season_of_discovery: 0,
  categories: [
    {
      name: 'Known recipes',
      season_of_discovery: false,
      recipes: [
        { recipe_id: 2657, name: 'Smelt Copper', known: true, crafted_item_id: null, wowhead: `${SEARCH}Smelt+Copper` },
      ],
    },
  ],
}
const book: RecipeBook = { professions: [mining, engineering], details_pending: 2 }
const professions: ProfessionsView = { level: 19, professions: [] }

describe('Professions', () => {
  it('lists recipes by category, the known ones marked, each linked to Wowhead', () => {
    render(<Professions professions={professions} book={book} />)

    const section = screen.getByRole('region', { name: 'Engineering recipes' })
    expect(within(section).getByText('1 known · 2 not learned yet')).toBeTruthy()
    expect(within(section).getByText('Scopes')).toBeTruthy()
    expect(within(section).getByText('1 of 3 known')).toBeTruthy()
    const crude = within(section).getByRole('link', { name: 'Crude Scope' })
    expect(crude.parentElement?.textContent).toBe('Crude Scopeknown')
    // Looked up: links to what it makes. Not yet: Wowhead's search for its name.
    expect(within(section).getByRole('link', { name: 'Standard Scope' }).getAttribute('href')).toBe(
      'https://www.wowhead.com/forever/item=4406',
    )
    expect(within(section).getByRole('link', { name: 'Accurate Scope' }).getAttribute('href')).toBe(
      `${SEARCH}Accurate+Scope`,
    )
    expect(within(section).getByRole('link', { name: 'Standard Scope' }).parentElement?.textContent).toBe(
      'Standard Scope',
    )
    expect(screen.getByText(/Looking up 2 recipes on Battle.net/)).toBeTruthy()
    expect(screen.getByText(/Battle.net doesn't say what skill each recipe needs/)).toBeTruthy()
  })

  it('hides Season of Discovery recipes until asked', () => {
    render(<Professions professions={professions} book={book} />)
    expect(screen.queryByText('Season of Discovery')).toBeNull()
    expect(screen.queryByRole('link', { name: 'Soul Vessel' })).toBeNull()

    fireEvent.click(screen.getByRole('checkbox', { name: /Show Season of Discovery recipes \(1\)/ }))
    expect(screen.getByText('Season of Discovery')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Soul Vessel' })).toBeTruthy()
  })

  it("says when a profession's full recipe list isn't loaded yet", () => {
    render(<Professions professions={professions} book={{ ...book, details_pending: 0 }} />)
    const section = screen.getByRole('region', { name: 'Mining recipes' })
    expect(within(section).getByText(/1 known · the recipes not learned yet appear after the next sync/)).toBeTruthy()
    expect(screen.queryByText(/Looking up/)).toBeNull()
  })

  it('has no Season of Discovery toggle when there are none, and a hint before a sync', () => {
    const { unmount } = render(
      <Professions professions={professions} book={{ professions: [mining], details_pending: 0 }} />,
    )
    expect(screen.queryByRole('checkbox')).toBeNull()
    unmount()
    render(<Professions professions={professions} book={{ professions: [], details_pending: 0 }} />)
    expect(screen.getByText(/No professions yet: sync the character/)).toBeTruthy()
  })
})
