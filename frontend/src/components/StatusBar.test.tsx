import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Status } from '../api'
import { StatusBar } from './StatusBar'

function status(refreshing: string[]): Status {
  return {
    character: 'nico-likeman',
    namespace: 'profile-forever-us',
    logged_in: true,
    token_expires_at: null,
    latest_snapshots: { profile: '2026-11-13T04:38:22' },
    refreshing,
  }
}

function renderBar(refreshing: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => Response.json(url === '/api/status' ? status(refreshing) : [])),
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
})
