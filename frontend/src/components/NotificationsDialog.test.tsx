import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AlertInfo, Destination, NotificationsView, SendResult } from '../api'
import { NotificationsDialog } from './NotificationsDialog'

const alerts: AlertInfo[] = [
  { kind: 'login_expired', audience: 'user', label: 'Login expired, syncs stopped' },
  { kind: 'level_up', audience: 'user', label: 'Level-ups' },
  { kind: 'job_failed', audience: 'system', label: 'A scheduled job failed' },
]
const mine: Destination = {
  id: 1,
  name: 'Phone',
  kind: 'discord_webhook',
  audience: 'user',
  url: '…/webhooks/123/••••',
  alerts: ['login_expired', 'level_up', 'job_failed'],
  enabled: true,
  last_sent_at: null,
  last_error: null,
}
const empty: NotificationsView = { destinations: [], alerts, recent: [], system_alerts_to_user: true }
const withMine: NotificationsView = {
  ...empty,
  destinations: [mine],
  recent: [
    {
      destination: 'Phone',
      kind: 'level_up',
      created_at: '2026-11-13T01:00:00',
      sent_at: '2026-11-13T01:00:05',
      failed: false,
      attempts: 1,
      last_error: null,
    },
  ],
}

const sent: SendResult = { ok: true, status: 204, error: null, retry_after: null, gone: false }

function stubFetch(view: NotificationsView, test: SendResult = sent) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/test')) return Response.json(test)
    if (init?.method === 'POST') return Response.json(withMine, { status: 201 })
    if (init?.method === 'PATCH') {
      const change = JSON.parse(String(init.body)) as Partial<Destination>
      return Response.json({ ...withMine, destinations: [{ ...mine, ...change }] })
    }
    if (init?.method === 'DELETE') return Response.json(empty)
    return Response.json(view)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function openDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NotificationsDialog />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Alerts' }))
}

function bodyOf(fetchMock: ReturnType<typeof stubFetch>, method: string): unknown {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === method)!
  return JSON.parse(String(call[1]!.body))
}

describe('NotificationsDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('adds a webhook destination', async () => {
    const fetchMock = stubFetch(empty)
    await openDialog()
    expect(await screen.findByText('No destinations yet.')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Phone' } })
    fireEvent.change(screen.getByLabelText('Webhook URL'), {
      target: { value: 'https://discord.com/api/webhooks/123/abc' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(bodyOf(fetchMock, 'POST')).toEqual({
      name: 'Phone',
      url: 'https://discord.com/api/webhooks/123/abc',
      audience: 'user',
    }))
    expect(await screen.findByText('…/webhooks/123/••••')).toBeTruthy()
    expect((screen.getByLabelText('Webhook URL') as HTMLInputElement).value).toBe('')
  })

  it('turns alerts and destinations off and on', async () => {
    const fetchMock = stubFetch(withMine)
    await openDialog()

    fireEvent.click(await screen.findByLabelText('Phone (user) Level-ups'))
    await waitFor(() => expect(bodyOf(fetchMock, 'PATCH')).toEqual({ alerts: ['login_expired', 'job_failed'] }))

    fireEvent.click(screen.getByLabelText('Phone (user) enabled'))
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH').at(-1)![1]!.body).toBe(
        JSON.stringify({ enabled: false }),
      ),
    )
  })

  it('sends a test and says when the webhook is gone', async () => {
    stubFetch(withMine, { ok: false, status: 404, error: 'HTTP 404', retry_after: null, gone: true })
    await openDialog()
    fireEvent.click(await screen.findByRole('button', { name: 'Send a test' }))
    expect(await screen.findByText(/Test failed: HTTP 404\. The webhook may have been deleted/)).toBeTruthy()
  })

  it('removes a destination after confirming', async () => {
    const fetchMock = stubFetch(withMine)
    vi.stubGlobal('confirm', () => true)
    await openDialog()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/notifications/destinations/1', expect.objectContaining({ method: 'DELETE' })),
    )
    expect(await screen.findByText('No destinations yet.')).toBeTruthy()
  })

  it('lists recent alerts and explains where system alerts go', async () => {
    stubFetch(withMine)
    await openDialog()
    expect(await screen.findByText('Recent alerts')).toBeTruthy()
    expect(screen.getAllByText('Level-ups').length).toBeGreaterThan(1) // the option and the row
    expect(screen.getByText(/^sent /)).toBeTruthy()
    expect(screen.getByText(/System alerts \(failed jobs, upstream errors\) go to your destinations/)).toBeTruthy()
  })
})
