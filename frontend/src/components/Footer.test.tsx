import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { About } from '../api'
import { Footer } from './Footer'

const about: About = {
  version: '0.1.0',
  source_url: 'https://git.example.org/me/planner',
  operator_contact: '',
  data: {
    name: 'Forever Companion',
    url: 'https://forevercompanion.io',
    sources: [
      { name: 'ForeverChanges', url: 'https://foreverchanges.pro' },
      { name: 'Wowhead', url: 'https://www.wowhead.com/forever' },
      { name: 'Zockify', url: 'https://www.zockify.com/forever/' },
    ],
  },
}

describe('Footer', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('credits Blizzard, Forever Companion and its sources once, and links the source code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(about)),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <Footer />
      </QueryClientProvider>,
    )

    const footer = await screen.findByRole('contentinfo')
    expect(footer.textContent).toBe(
      'Item and dungeon data from Forever Companion, gathered from ForeverChanges, Wowhead and Zockify and ' +
        'checked in game by players. Fan-made, not affiliated with Blizzard Entertainment.' +
        'Character Planner 0.1.0 · Source (AGPL-3.0) · Privacy',
      "Character and game data from Blizzard Entertainment's Battle.net API. " +
        'Item and dungeon data from Forever Companion, gathered from ForeverChanges, Wowhead and Zockify and ' +
        'checked in game by players.' +
        'Fan-made, not affiliated with or endorsed by Blizzard Entertainment.' +
        'Character Planner 0.1.0 · Source (AGPL-3.0)',
    )
    const link = (name: string) => screen.getByRole('link', { name }).getAttribute('href')
    // Blizzard's API terms (§2 item 13): Blizzard named as the source, with a link.
    expect(link("Blizzard Entertainment's Battle.net API")).toBe('https://develop.battle.net/')
    expect(link('Forever Companion')).toBe('https://forevercompanion.io')
    expect(link('Zockify')).toBe('https://www.zockify.com/forever/')
    // SOURCE_URL: a fork links its own code.
    expect(link('Source')).toBe('https://git.example.org/me/planner')
    // The privacy notice (#133), on every page.
    expect(link('Privacy')).toBe('#privacy')
  })
})
