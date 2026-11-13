import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LookAhead as LookAheadData, LookAheadEvent } from '../api'
import { LookAhead } from './LookAhead'

function event(overrides: Partial<LookAheadEvent>): LookAheadEvent {
  return {
    kind: 'talent',
    title: 'Talent point',
    detail: null,
    essential: false,
    pinned: false,
    locked: false,
    link: null,
    ...overrides,
  }
}

// Level 19, from the real data: what levels 20 and 22 bring.
const data: LookAheadData = {
  level: 19,
  levels: 5,
  groups: [
    {
      level: 20,
      events: [
        event({
          kind: 'dungeon',
          title: 'Shadowfang Keep',
          detail: 'levels 20-30, Silverpine Forest',
          link: 'https://forevercompanion.io/dungeons/shadowfang-keep',
        }),
        event({ kind: 'class_quest', title: 'Class quest: Yorus Barleybrew', detail: 'Fire Hardened armor pieces' }),
        event({ kind: 'profession', title: 'Expert Engineering', detail: 'cap 225; needs 125 skill, 21 to go' }),
        event({ title: 'Talent: Toughness rank 1' }),
      ],
    },
    {
      level: 22,
      events: [
        event({ kind: 'target', title: 'Main Hand: Doomspike', detail: '+15.7 score · Wailing Caverns', pinned: true }),
        event({ kind: 'dungeon', title: 'City of Dalaran', locked: true }),
        event({ kind: 'class_quest', title: 'Class quest: The Islander', essential: true }),
      ],
    },
  ],
}

function renderLookAhead() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LookAhead />
    </QueryClientProvider>,
  )
}

describe('LookAhead', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    window.localStorage.clear()
    fetchMock = vi.fn(async () => Response.json(data))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists each coming level with what it brings', async () => {
    renderLookAhead()

    const twenty = await screen.findByRole('list', { name: 'Level 20' })
    const kinds = within(twenty)
      .getAllByRole('listitem')
      .map((li) => li.querySelector('.look-ahead-kind')?.textContent)
    expect(kinds).toEqual(['Dungeon', 'Quest', 'Profession', 'Talent'])
    expect(within(twenty).getByRole('link', { name: 'Shadowfang Keep' }).getAttribute('href')).toBe(
      'https://forevercompanion.io/dungeons/shadowfang-keep',
    )
    expect(within(twenty).getByText('cap 225; needs 125 skill, 21 to go')).toBeTruthy()

    const later = screen.getByRole('list', { name: 'Level 22' })
    expect(within(later).getByText('pinned')).toBeTruthy()
    expect(within(later).getByText('not open yet')).toBeTruthy()
    expect(within(later).getByText('essential')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/look-ahead?levels=5', undefined)
  })

  it('asks for another range and remembers it', async () => {
    renderLookAhead()
    await screen.findByRole('list', { name: 'Level 20' })

    fireEvent.change(screen.getByRole('combobox'), { target: { value: '8' } })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/look-ahead?levels=8', undefined))
    expect(window.localStorage.getItem('look-ahead-levels')).toBe('8')
  })

  it('starts from the remembered range', async () => {
    window.localStorage.setItem('look-ahead-levels', '3')
    renderLookAhead()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/look-ahead?levels=3', undefined))
  })

  it('explains an empty look-ahead', async () => {
    fetchMock.mockImplementation(async () => Response.json({ level: null, levels: 5, groups: [] }))
    renderLookAhead()
    expect(await screen.findByText('Sync your character to see what the next levels bring.')).toBeTruthy()
  })
})
