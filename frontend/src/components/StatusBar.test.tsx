import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Status } from '../api'
import { StatusBar } from './StatusBar'

function status(refreshing: string[], extra: Partial<Status> = {}): Status {
  return {
    character: 'nico-likeman',
    namespace: 'profile-forever-us',
    can_sync: true,
    character_found: true,
    logged_in: false,
    token_expires_at: null,
    latest_snapshots: { profile: '2026-11-13T04:38:22' },
    refreshing,
    ...extra,
  }
}

function renderBar(refreshing: string[], extra: Partial<Status> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => Response.json(url === '/api/status' ? status(refreshing, extra) : [])),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <StatusBar />
    </QueryClientProvider>,
  )
}

describe('StatusBar', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('says what is loading in the background', async () => {
    renderBar(['enchants', 'pool'])
    expect((await screen.findByRole('status')).textContent).toBe(
      'Loading enchant data and the item pool in the background…',
    )
  })

  it('says nothing when nothing is loading', async () => {
    renderBar([])
    await screen.findByText('Sync now')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('syncs without a login (#107): no login button', async () => {
    renderBar([], { logged_in: false })
    expect(await screen.findByText('Sync now')).toBeTruthy()
    expect(screen.queryByText(/Log in/)).toBeNull()
  })

  it('says when the Battle.net client is missing', async () => {
    renderBar([], { can_sync: false })
    expect((await screen.findByRole('alert')).textContent).toMatch(/^No Battle.net client: set BNET_CLIENT_ID/)
    expect(screen.queryByText('Sync now')).toBeNull()
  })

  it('says when the last sync could not find the character', async () => {
    renderBar([], { character_found: false })
    expect((await screen.findByRole('alert')).textContent).toMatch(
      /^Battle.net can't find nico-likeman: check its name and region/,
    )
  })

  it('shows the cooldown as a note, not a failure (#17)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/sync' && init?.method === 'POST') {
          return Response.json({ detail: 'Synced recently: sync again in about 10 minutes' }, { status: 429 })
        }
        return Response.json(url === '/api/status' ? status([]) : [])
      }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <StatusBar />
      </QueryClientProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
    const note = await screen.findByText('Synced recently: sync again in about 10 minutes')
    expect(note.className).toBe('muted')
    expect(screen.queryByText(/Sync failed/)).toBeNull()
  })
})
