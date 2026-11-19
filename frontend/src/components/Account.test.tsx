import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccountView, Me } from '../api'
import { Account } from './Account'

const SINGLE: Me = {
  users: false,
  signed_in: false,
  admin: false,
  role: null,
  permissions: [],
  signups_open: false,
}
const SIGNED_IN: Me = { ...SINGLE, users: true, signed_in: true, role: 'user' }

const brumboldt = {
  id: 1,
  name: 'Brumboldt Doomlet',
  region: 'us',
  character_class: 'Warrior',
  level: 19,
  default: true,
  last_sync: '2026-11-19T12:00:00Z',
  guild: 'Daves Discount Meats',
  in_guild_view: true,
  game_data_at: null,
}
const lilalx = { ...brumboldt, id: 2, name: 'Lilalx', level: 12, default: false, in_guild_view: false }

type Call = { url: string; method: string; character: string | null }

function show(me: Me, view: AccountView) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({ url, method: init?.method ?? 'GET', character: headers['X-Character-Id'] ?? null })
      if (url === '/api/me') return Response.json(me)
      if (url === '/api/account') return Response.json(view)
      if (url === '/api/notifications') {
        return Response.json({ destinations: [], alerts: [], recent: [], system_alerts_to_user: false })
      }
      if (url === '/api/discord') return Response.json({ available: false })
      if (url === '/api/builds')
        return Response.json({ class_name: 'Warrior', builds: [], current: null, customised: [] })
      if (url === '/api/sync') return Response.json({ profile: 200 })
      if (url === '/api/character') return Response.json({ removed: { character: 1 } })
      return Response.json([])
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Account />
    </QueryClientProvider>,
  )
  return calls
}

describe('Account', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists every character with its sync, guild and game data', async () => {
    show(SINGLE, { users: false, account_id: null, role: null, characters: [brumboldt, lilalx] })
    const row = (await screen.findByText('Brumboldt Doomlet')).closest('tr')!
    expect(row.textContent).toContain('level 19 · Warrior · US')
    expect(within(row).getByText('default')).toBeTruthy()
    expect(within(row).getByText('in the guild view')).toBeTruthy()
    expect(within(row).getByText('none')).toBeTruthy() // no game data
    expect(screen.getByRole('heading', { name: 'Guilds' })).toBeTruthy()
    expect(screen.getByText(/Brumboldt Doomlet, Lilalx/)).toBeTruthy() // no guild view without users
    expect(screen.getByRole('link', { name: 'Download my data' }).getAttribute('href')).toBe('/api/account/export')
    expect(screen.getByRole('heading', { name: 'Alerts' })).toBeTruthy()
    // Without users: no sign-in, no account to delete.
    expect(screen.queryByRole('heading', { name: 'Sign-in' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete my account' })).toBeNull()
  })

  it('syncs and removes one character, named in the request', async () => {
    const calls = show(SINGLE, { users: false, account_id: null, role: null, characters: [brumboldt, lilalx] })
    const row = (await screen.findByText('Lilalx')).closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Sync Lilalx' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/sync', method: 'POST', character: '2' }))

    fireEvent.click(within(row).getByRole('button', { name: 'Remove…' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(within(row).getByRole('button', { name: 'Yes, remove it' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/character', method: 'DELETE', character: '2' }))
  })

  it('shows the sign-in and account deletion with users on', async () => {
    show(SIGNED_IN, { users: true, account_id: 2002, role: 'user', characters: [] })
    expect(await screen.findByText(/Signed in with Battle.net account 2002\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Delete my account' })).toBeTruthy()
    expect(screen.getByText('No characters yet.')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Guilds' })).toBeNull()
  })
})
