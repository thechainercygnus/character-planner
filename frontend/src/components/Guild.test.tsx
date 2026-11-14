import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GuildView } from '../api'
import { Guild } from './Guild'

const GUILD = { id: 670649, name: 'Daves Discount Meats' }

const joined: GuildView = {
  guild: GUILD,
  opted_in: true,
  role: null,
  members: [
    {
      character_id: 1,
      name: 'Brum Doomlet',
      character_class: 'Warrior',
      spec: 'Protection',
      role: 'tank',
      level: 19,
      yours: true,
    },
    { character_id: 3, name: 'Fizz Bang', character_class: 'Mage', spec: 'Fire', role: 'dps', level: 31, yours: false },
  ],
  going: [1, 3],
  roles: { tank: 1, healer: 0, dps: 1 },
  missing_roles: ['healer'],
  dungeons: [
    {
      dungeon_id: 'deadmines',
      dungeon: 'The Deadmines',
      min_level: 17,
      max_level: 26,
      total_gain: 11.5,
      in_range: [1],
      needs: { '1': [{ item: 'Cape of the Brotherhood', item_id: 5193, slot: 'BACK', score_gain: 6 }] },
    },
  ],
}

function serve(view: GuildView) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null })
      return Response.json(view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Guild />
    </QueryClientProvider>,
  )
  return calls
}

describe('Guild', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says so when the character has no guild', async () => {
    serve({ ...joined, guild: null, opted_in: false, members: [], dungeons: [] })
    expect(await screen.findByText(/isn't in a guild/)).toBeTruthy()
  })

  it('offers to join, with a role, and shows nobody until then', async () => {
    const calls = serve({ ...joined, opted_in: false, members: [], going: [], dungeons: [], missing_roles: [] })
    expect(await screen.findByRole('heading', { name: 'Daves Discount Meats' })).toBeTruthy()
    expect(screen.queryByText('Fizz Bang')).toBeNull()
    fireEvent.change(screen.getByRole('combobox', { name: 'Your role' }), { target: { value: 'healer' } })
    fireEvent.click(screen.getByRole('button', { name: 'Join the guild view' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')).toEqual({
      url: '/api/guild/membership',
      method: 'PUT',
      body: { opted_in: true, role: 'healer' },
    })
  })

  it('shows the members, a missing role and the best runs', async () => {
    serve(joined)
    expect(await screen.findByText('Fizz Bang')).toBeTruthy()
    expect(screen.getByText('(yours)')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toBe('No healer among the members going.')
    expect(screen.getByText('The Deadmines')).toBeTruthy()
    expect(screen.getByText(/\+11\.5 · 1 of 2 in range/)).toBeTruthy()
    expect(screen.getByText(/Cape of the Brotherhood \(\+6\.0\)/)).toBeTruthy()
  })

  it('asks again for just the members going', async () => {
    const calls = serve(joined)
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Fizz Bang is going' }))
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/guild?going=1'))
  })

  it('leaves the guild view', async () => {
    const calls = serve(joined)
    fireEvent.click(await screen.findByRole('button', { name: 'Leave the guild view' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ opted_in: false, role: null }))
  })
})
