import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Me, Status } from './api'
import App from './App'
import { Privacy } from './components/Privacy'
import { StatusBar } from './components/StatusBar'

const STATUS: Status = {
  character: 'brumboldt-doomlet',
  namespace: 'profile-forever-us',
  can_sync: true,
  character_found: true,
  logged_in: true,
  token_expires_at: null,
  latest_snapshots: {},
  refreshing: [],
}

/** An API with users on (#16): signed out, everything but the public routes is 401. */
function serve(me: Me) {
  const calls: { url: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' })
      if (url === '/api/me') return Response.json(me)
      if (url === '/api/about') {
        return Response.json({
          version: '0.5.0',
          source_url: 'https://example.org',
          operator_contact: '',
          data: { name: 'Forever Companion', url: 'https://forevercompanion.io', sources: [] },
        })
      }
      if (url === '/api/logout') return new Response(null, { status: 204 })
      if (url === '/api/account' && init?.method === 'DELETE') {
        return me.admin
          ? Response.json({ detail: 'Hand the instance over first: other users still need an admin' }, { status: 409 })
          : Response.json({ removed: { user: 1 } })
      }
      if (!me.signed_in && !url.startsWith('/api/about') && !url.startsWith('/api/guest')) {
        return Response.json({ detail: 'Sign in with Battle.net' }, { status: 401 })
      }
      if (url === '/api/status') return Response.json(STATUS)
      return Response.json([])
    }),
  )
  return calls
}

function show(element: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
}

const SIGNED_OUT: Me = { users: true, signed_in: false, admin: false, signups_open: false }
const GUILDMATE: Me = { users: true, signed_in: true, admin: false, signups_open: false }
const ADMIN: Me = { ...GUILDMATE, admin: true }

describe('With users on', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.location.hash = ''
  })

  it('a signed-out visitor sees the Battle.net sign-in, and nothing else', async () => {
    serve(SIGNED_OUT)
    show(<App />)
    const signIn = await screen.findByRole('link', { name: 'Sign in with Battle.net' })
    expect(signIn.getAttribute('href')).toBe('/auth/login')
    expect(screen.getByText(/invite-only/)).toBeTruthy()
    expect(screen.queryByText(/Couldn't load/)).toBeNull()
  })

  it('guest mode still works signed out', async () => {
    window.location.hash = '#guest'
    serve(SIGNED_OUT)
    show(<App />)
    expect(await screen.findByRole('heading', { name: 'Plan your WoW Forever character' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Sign in with Battle.net' })).toBeNull()
  })

  it("hides the admin's instance-wide actions from everyone else", async () => {
    serve(GUILDMATE)
    show(<StatusBar />)
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Alerts' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Refresh item pool' })).toBeNull()
  })

  it('shows them to the admin', async () => {
    serve(ADMIN)
    show(<StatusBar />)
    expect(await screen.findByRole('button', { name: 'Refresh item pool' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
  })

  it('deletes the account from the privacy page, after a second click', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const calls = serve(GUILDMATE)
    show(<Privacy />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete my account' }))
    expect(calls.some((c) => c.url === '/api/account')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Yes, delete my account' }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('/'))
    expect(calls).toContainEqual({ url: '/api/account', method: 'DELETE' })
  })

  it("says why the admin can't go first", async () => {
    serve(ADMIN)
    show(<Privacy />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete my account' }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes, delete my account' }))
    expect(await screen.findByText(/Hand the instance over first/)).toBeTruthy()
  })

  it('signs out', async () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    const calls = serve(GUILDMATE)
    show(<StatusBar />)
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(reload).toHaveBeenCalled())
    expect(calls).toContainEqual({ url: '/api/logout', method: 'POST' })
  })
})
