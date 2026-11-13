import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GuestOptions, Status } from '../api'
import { recommendations } from '../test/fixtures'
import { Landing } from './Landing'

const options: GuestOptions = {
  classes: [{ key: 'warrior', name: 'Warrior' }],
  presets: [
    { key: 'leveling-tank', name: 'Leveling tank' },
    { key: 'solo-dps', name: 'Solo DPS' },
  ],
  factions: ['alliance', 'horde'],
}

function status(loggedIn: boolean): Status {
  return { character: 'Brumboldt Doomlet', namespace: 'profile-forever-us', logged_in: loggedIn, token_expires_at: null, latest_snapshots: {} }
}

function stubFetch(loggedIn = false) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/status') return Response.json(status(loggedIn))
    if (url === '/api/guest') return Response.json(options)
    if (url.startsWith('/api/guest/recommendations')) return Response.json(recommendations)
    if (url === '/api/sync' && init?.method === 'POST') return Response.json({ profile: 200 })
    return Response.json([])
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderLanding(hasCharacter = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Landing hasCharacter={hasCharacter} />
    </QueryClientProvider>,
  )
}

function guestCalls(fetchMock: ReturnType<typeof stubFetch>): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.startsWith('/api/guest/recommendations'))
    .map((url) => new URLSearchParams(url.split('?')[1]))
}

describe('Landing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('explains the planner and how to log in', async () => {
    stubFetch()
    renderLanding()

    expect(screen.getByText('Plan your WoW Forever character')).toBeTruthy()
    expect(screen.getByText('Log in with Battle.net').getAttribute('href')).toBe('/auth/login')
    expect(screen.getByText(/only asks to read your profile/)).toBeTruthy()
  })

  it('offers a sync when logged in without data', async () => {
    const fetchMock = stubFetch(true)
    renderLanding()

    fireEvent.click(await screen.findByText('Sync now'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/sync', expect.objectContaining({ method: 'POST' })))
  })

  it('shows guest recommendations for the chosen class, level, faction and play style', async () => {
    const fetchMock = stubFetch()
    renderLanding()

    expect(await screen.findByText('Best items for your level')).toBeTruthy()
    expect(Object.fromEntries(guestCalls(fetchMock)[0])).toEqual({
      class: 'warrior',
      level: '15',
      faction: 'alliance',
      preset: 'leveling-tank',
    })

    fireEvent.change(screen.getByLabelText('Level'), { target: { value: '22' } })
    fireEvent.change(screen.getByLabelText('Faction'), { target: { value: 'horde' } })
    fireEvent.change(screen.getByLabelText('Play style'), { target: { value: 'solo-dps' } })
    await waitFor(() =>
      expect(Object.fromEntries(guestCalls(fetchMock).at(-1)!)).toEqual({
        class: 'warrior',
        level: '22',
        faction: 'horde',
        preset: 'solo-dps',
      }),
    )
    expect(screen.getByText('Dungeons worth running', { exact: false })).toBeTruthy()
    expect(screen.queryByText('Equipped')).toBeNull()
  })

  it("doesn't ask for items with a bad level", async () => {
    const fetchMock = stubFetch()
    renderLanding()
    await screen.findByText('Best items for your level')
    const before = guestCalls(fetchMock).length

    fireEvent.change(screen.getByLabelText('Level'), { target: { value: '90' } })
    expect(screen.getByText('Level must be a whole number from 1 to 80.')).toBeTruthy()
    expect(guestCalls(fetchMock).length).toBe(before)
  })

  it('links back to the character when there is one', async () => {
    stubFetch()
    renderLanding(true)
    expect(screen.getByText('← Back to your character').getAttribute('href')).toBe('#upgrades')
    expect(screen.queryByText('Plan your WoW Forever character')).toBeNull()
  })
})
