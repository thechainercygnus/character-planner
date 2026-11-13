import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemChoice, Recommendations as RecommendationsData } from '../api'
import { candidate, girdle, laterBelt, recommendations } from '../test/fixtures'
import { Recommendations } from './Recommendations'

const hidden: ItemChoice = {
  item_id: 5193,
  name: 'Cape of the Brotherhood',
  choice: 'dismissed',
  created_at: '2026-11-12T10:00:00',
}

/** fetch stub: GET /api/choices answers `choices`; writes answer with an empty list. */
function stubFetch(choices: ItemChoice[] = []) {
  const fetchMock = vi.fn(async (_path: string, init?: RequestInit) =>
    Response.json(init?.method ? [] : choices),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderRecommendations(data: RecommendationsData = recommendations) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Recommendations data={data} />
    </QueryClientProvider>,
  )
}

describe('Recommendations', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows one compact row per slot with an upgrade', () => {
    stubFetch()
    renderRecommendations()

    expect(screen.getByText('1 of 3 slots have an upgrade in reach', { exact: false })).toBeTruthy()
    expect(screen.getByText('(5 more without stats yet)', { exact: false })).toBeTruthy()
    expect(screen.getByText('Kindlegem Girdle').closest('a')?.getAttribute('href')).toContain('item=1')
    expect(screen.getByText('your target')).toBeTruthy()
    expect(screen.getByText('+9.7')).toBeTruthy()
    // Details stay hidden until the row is opened.
    expect(screen.queryByText('Hall of Thanes – Plunder')).toBeNull()
    expect(screen.queryByText('Later Belt')).toBeNull()
  })

  it('lists slots without upgrades on one line', () => {
    stubFetch()
    renderRecommendations()

    expect(screen.getByText('No upgrades in reach: Neck, Trinket 2')).toBeTruthy()
  })

  it('opens a row to show sources, changes and other options', () => {
    stubFetch()
    renderRecommendations()

    fireEvent.click(screen.getByRole('button', { name: 'Show details for Waist' }))

    expect(screen.getByText('Hall of Thanes – Plunder')).toBeTruthy()
    expect(screen.getByText('+4 item level · +27 armor · +7 Stamina')).toBeTruthy()
    expect(screen.getByText('Later Belt')).toBeTruthy()
    expect(screen.getByText('Quest: The Defias Brotherhood (The Deadmines), choice')).toBeTruthy()
    expect(screen.getByText('level 20')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Hide details for Waist' }))
    expect(screen.queryByText('Later Belt')).toBeNull()
  })

  it('pins an item as a target and dismisses another', async () => {
    const fetchMock = stubFetch()
    renderRecommendations()
    fireEvent.click(screen.getByRole('button', { name: 'Show details for Waist' }))

    // The girdle is already a target from gear_targets.yaml: it offers Pin, not Make target.
    const [laterBeltTarget, ...others] = screen.getAllByRole('button', { name: 'Make target' })
    expect(others).toEqual([])
    expect(screen.getAllByRole('button', { name: 'Pin' })).toHaveLength(1)
    fireEvent.click(laterBeltTarget)
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/targets/pins', expect.objectContaining({ method: 'POST' })),
    )
    const post = fetchMock.mock.calls.find(([path]) => path === '/api/targets/pins')!
    // Pinned into the row's slot (ADR 0014).
    expect(JSON.parse(String(post[1]?.body))).toEqual({ item_id: 2, slot: 'WAIST' })

    fireEvent.click(screen.getAllByRole('button', { name: 'Never suggest' })[0])
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) => path === '/api/choices/270230')
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ choice: 'dismissed', name: 'Kindlegem Girdle' })
    })
  })

  it('unpins a pinned item', async () => {
    const fetchMock = stubFetch()
    const pinned = {
      ...recommendations,
      rows: [
        {
          slot: 'WAIST',
          equipped: null,
          candidates: [candidate(girdle, 9.7), candidate(laterBelt, -1.5, { is_target: true, pinned: true })],
        },
      ],
    }
    renderRecommendations(pinned)
    fireEvent.click(screen.getByRole('button', { name: 'Show details for Waist' }))

    expect(screen.getByText('-1.5').className).toContain('verdict-sidegrade')
    fireEvent.click(screen.getByRole('button', { name: 'Unpin' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/targets/pins/2', expect.objectContaining({ method: 'DELETE' })),
    )
  })

  it('lists items never to suggest, with an undo', async () => {
    const fetchMock = stubFetch([hidden])
    renderRecommendations()

    expect(await screen.findByText('Never suggested')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Suggest Cape of the Brotherhood again' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/choices/5193', expect.objectContaining({ method: 'DELETE' })),
    )
  })

  it('explains how to build the pool when it is empty', () => {
    stubFetch()
    renderRecommendations({ ...recommendations, rows: [], dungeons: [], considered: 0, unscored: 0 })

    expect(screen.getByText('No item pool yet.', { exact: false })).toBeTruthy()
  })
})

describe('Recommendations in guest mode', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('leaves out what is worn and the buttons that store choices', () => {
    stubFetch()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <Recommendations data={recommendations} guest />
      </QueryClientProvider>,
    )
    expect(screen.getByText('Best items for your level')).toBeTruthy()
    expect(screen.queryByText('Equipped')).toBeNull()
    fireEvent.click(screen.getAllByRole('button', { name: /^Show details/ })[0])
    expect(screen.queryByText('Never suggest')).toBeNull()
    expect(screen.queryByText('Make target')).toBeNull()
  })
})
