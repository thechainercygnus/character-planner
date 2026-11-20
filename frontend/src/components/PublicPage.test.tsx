import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { publicLink, publicToken, type PublicCharacter, type PublicPageState } from '../api'
import { PublicPage, PublicPageControl } from './PublicPage'

const TOKEN = 'abcdefghijklmnopqrstuvwxyz012345'

const character: PublicCharacter = {
  name: 'Brumboldt',
  surname: 'Doomlet',
  level: 18,
  race: 'Gnome',
  character_class: 'Warrior',
  guild: 'Daves Discount Meats',
  equipped_item_level: 16.7,
  gear_slots_filled: 13,
  captured_at: '2026-11-13T17:22:00',
  stats: null,
  professions: [{ name: 'Engineering', skill: 104, max_skill: 150, primary: true }],
  specialization: null,
  equipment: [],
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

type Handler = (url: string, init?: RequestInit) => Response
function stubFetch(handler: Handler) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => handler(url, init))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const about = Response.json({
  version: '0.8.2',
  source_url: 'https://example.org',
  operator_contact: '',
  data: { name: 'Forever Companion', url: 'https://forevercompanion.io', sources: [] },
})

describe('public page links', () => {
  it('carries the token in the fragment, and reads it back', () => {
    expect(publicLink(TOKEN)).toBe(`${window.location.origin}/#public=${TOKEN}`)
    expect(publicToken(`#public=${TOKEN}`)).toBe(TOKEN)
    expect(publicToken('#character')).toBeNull()
    expect(publicToken('#public=<script>')).toBeNull()
  })
})

describe('PublicPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the snapshot, posting the token in the body, never the URL', async () => {
    const fetch = stubFetch((url) => (url === '/api/public/character' ? Response.json(character) : about.clone()))
    wrap(<PublicPage token={TOKEN} />)

    expect(await screen.findByRole('heading', { name: 'Brumboldt Doomlet' })).toBeTruthy()
    expect(screen.getByText(/shared by this character's owner/)).toBeTruthy()
    expect(screen.getByText('Engineering')).toBeTruthy()
    const call = fetch.mock.calls.find(([url]) => url === '/api/public/character')!
    expect(call[1]?.method).toBe('POST')
    expect(call[1]?.body).toBe(JSON.stringify({ token: TOKEN }))
    expect(fetch.mock.calls.every(([url]) => !url.includes(TOKEN))).toBe(true)
  })

  it('says so when the link is off or replaced', async () => {
    stubFetch((url) =>
      url === '/api/public/character' ? Response.json({ detail: 'gone' }, { status: 404 }) : about.clone(),
    )
    wrap(<PublicPage token={TOKEN} />)
    expect(await screen.findByText("This page isn't shared, or its link has changed.")).toBeTruthy()
  })

  it('says when there is nothing to show after the 30-day rule', async () => {
    stubFetch((url) =>
      url === '/api/public/character' ? Response.json({ ...character, name: null, level: null }) : about.clone(),
    )
    wrap(<PublicPage token={TOKEN} />)
    expect(await screen.findByText(/hasn't been synced in the last 30 days/)).toBeTruthy()
  })
})

describe('PublicPageControl', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('turns the page on, shows the link, and makes a new one', async () => {
    let state: PublicPageState = { enabled: false, token: null, created_at: null }
    const fetch = stubFetch((url, init) => {
      if (url === '/api/character/public-page' && init?.method === 'PUT') {
        state = { enabled: true, token: TOKEN, created_at: '2026-11-22T00:00:00Z' }
      }
      if (url === '/api/character/public-page/regenerate') {
        state = { ...state, token: 'Z'.repeat(32) }
      }
      return Response.json(state)
    })
    wrap(<PublicPageControl />)

    const toggle = await screen.findByRole('checkbox', { name: 'Share a public page' })
    expect((toggle as HTMLInputElement).checked).toBe(false)
    expect(screen.queryByRole('textbox', { name: 'Public page link' })).toBeNull()

    fireEvent.click(toggle)
    const link = await screen.findByRole('textbox', { name: 'Public page link' })
    expect((link as HTMLInputElement).value).toBe(publicLink(TOKEN))
    const put = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')!
    expect(put[1]?.body).toBe(JSON.stringify({ enabled: true }))

    fireEvent.click(screen.getByRole('button', { name: 'New link' }))
    expect(await screen.findByDisplayValue(publicLink('Z'.repeat(32)))).toBeTruthy()
  })

  it('turns it off, and the link goes', async () => {
    let state: PublicPageState = { enabled: true, token: TOKEN, created_at: '2026-11-22T00:00:00Z' }
    stubFetch((_url, init) => {
      if (init?.method === 'PUT') state = { enabled: false, token: null, created_at: null }
      return Response.json(state)
    })
    wrap(<PublicPageControl />)
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Share a public page' }))
    await vi.waitFor(() => expect(screen.queryByRole('textbox', { name: 'Public page link' })).toBeNull())
  })
})
