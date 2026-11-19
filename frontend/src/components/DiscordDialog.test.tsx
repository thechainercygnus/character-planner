import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AlertInfo, DiscordLink, DiscordView } from '../api'
import { DiscordSettings } from './DiscordDialog'

const alerts: AlertInfo[] = [
  { kind: 'level_up', audience: 'user', label: 'Level-ups' },
  { kind: 'new_upgrade', audience: 'user', label: 'New upgrades worth having' },
]
const link: DiscordLink = {
  name: 'Brum',
  alerts: ['level_up', 'new_upgrade'],
  enabled: true,
  last_error: null,
  last_sent_at: null,
}
const unlinked: DiscordView = {
  available: true,
  invite_url: 'https://discord.gg/planner',
  linked: null,
  alerts,
  in_server: null,
}
const linked: DiscordView = { ...unlinked, linked: link }

function serve(view: DiscordView, answers: Partial<Record<string, DiscordView>> = {}) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
      return Response.json(answers[`${method} ${url}`] ?? view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={client}>
      <DiscordSettings />
    </QueryClientProvider>,
  )
  return { calls, container }
}

/** Wait for the settings to load: My account shows them in place (#260), no dialog to open. */
async function open() {
  await screen.findByText(/as private messages from the planner's bot/)
}

describe('DiscordSettings', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows nothing when the instance has no bot', async () => {
    const { calls, container } = serve({ ...unlinked, available: false })
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(container.textContent).toBe('')
  })

  it('offers to link, and the server to join', async () => {
    serve(unlinked)
    await open()
    expect(screen.getByRole('link', { name: 'Link Discord' }).getAttribute('href')).toBe('/auth/discord/login')
    expect(screen.getByRole('link', { name: "Join the planner's Discord server" }).getAttribute('href')).toBe(
      'https://discord.gg/planner',
    )
  })

  it('chooses alerts and pauses DMs', async () => {
    const { calls } = serve(linked)
    await open()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Level-ups' }))
    await waitFor(() => expect(calls.at(-1)).toMatchObject({ method: 'PATCH', body: { alerts: ['new_upgrade'] } }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Send me DMs' }))
    await waitFor(() => expect(calls.at(-1)).toMatchObject({ method: 'PATCH', body: { enabled: false } }))
  })

  it('says why DMs are paused, and when a test shows they left the server', async () => {
    const refused = 'Discord refused the DM: fix that, then send a test to resume.'
    serve(
      { ...linked, linked: { ...link, enabled: false, last_error: refused } },
      { 'POST /api/discord/test': { ...linked, linked: { ...link, last_error: refused }, in_server: false } },
    )
    await open()
    expect((await screen.findByRole('alert')).textContent).toBe(refused)
    fireEvent.click(screen.getByRole('button', { name: 'Send a test DM' }))
    expect((await screen.findByRole('status')).textContent).toMatch(/not in the bot's server/)
  })

  it('reports a test that got through', async () => {
    serve(linked)
    await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Send a test DM' }))
    expect(await screen.findByText('Test sent. Check your DMs.')).toBeTruthy()
  })

  it('unlinks after asking', async () => {
    vi.stubGlobal('confirm', () => true)
    const { calls } = serve(linked, { 'DELETE /api/discord': unlinked })
    await open()
    fireEvent.click(await screen.findByRole('button', { name: 'Unlink Discord' }))
    expect(await screen.findByRole('link', { name: 'Link Discord' })).toBeTruthy()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })
})
