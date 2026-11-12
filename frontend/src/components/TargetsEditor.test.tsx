import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GearTarget, GearTargets, PoolView } from '../api'
import { girdle } from '../test/fixtures'
import { TargetsEditor } from './TargetsEditor'

function target(slot: string, item: string, overrides: Partial<GearTarget> = {}): GearTarget {
  return {
    slot,
    item,
    source: 'Somewhere',
    priority: null,
    item_id: null,
    item_level: null,
    armor_type: null,
    armor: null,
    stats: {},
    ...overrides,
  }
}

const targets: GearTargets = {
  brackets: [
    { min_level: 15, targets: [target('WAIST', 'Old Belt'), target('BACK', 'Old Cape', { item_id: 7, armor: 20 })] },
  ],
}
const pool: PoolView = { level: 18, faction: 'alliance', window: [15, 28], items: [girdle] }

function stubFetch() {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return Response.json(JSON.parse(String(init.body)))
    return Response.json(url === '/api/pool' ? pool : targets)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function openEditor(customised = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TargetsEditor customised={customised} />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /^Edit targets/ }))
  await screen.findByLabelText('Bracket 1 target 1 item')
}

function savedBody(fetchMock: ReturnType<typeof stubFetch>): GearTargets {
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  return JSON.parse(String(put[1]!.body)) as GearTargets
}

describe('TargetsEditor', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reorders, removes and adds targets, keeping hand-entered fields', async () => {
    const fetchMock = stubFetch()
    await openEditor()

    fireEvent.click(screen.getByRole('button', { name: 'Move bracket 1 target 2 up' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove bracket 1 target 2' })) // Old Belt
    fireEvent.click(screen.getByText('Add target'))
    fireEvent.change(screen.getByLabelText('Bracket 1 target 2 slot'), { target: { value: 'NECK' } })
    fireEvent.change(screen.getByLabelText('Bracket 1 target 2 item'), { target: { value: 'Locket' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/targets', expect.objectContaining({ method: 'PUT' })))
    const saved = savedBody(fetchMock)
    expect(saved.brackets[0].min_level).toBe(15)
    expect(saved.brackets[0].targets.map((t) => [t.slot, t.item, t.item_id, t.armor])).toEqual([
      ['BACK', 'Old Cape', 7, 20],
      ['NECK', 'Locket', null, null],
    ])
  })

  it('fills the item id and source from the pool by name', async () => {
    const fetchMock = stubFetch()
    await openEditor()

    fireEvent.click(screen.getByText('Add target'))
    fireEvent.change(screen.getByLabelText('Bracket 1 target 3 item'), { target: { value: 'kindlegem girdle' } })
    expect((screen.getByLabelText('Bracket 1 target 3 source') as HTMLInputElement).value).toBe(
      'Hall of Thanes – Plunder',
    )
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/targets', expect.objectContaining({ method: 'PUT' })))
    expect(savedBody(fetchMock).brackets[0].targets[2].item_id).toBe(girdle.item_id)
  })

  it('adds a bracket above the highest and blocks bad levels and blank names', async () => {
    stubFetch()
    await openEditor()

    fireEvent.click(screen.getByText('Add bracket'))
    expect((screen.getByLabelText('Bracket 2 level') as HTMLInputElement).value).toBe('20')
    fireEvent.change(screen.getByLabelText('Bracket 2 level'), { target: { value: '15' } })
    expect(screen.getByText('There are two brackets for level 15.')).toBeTruthy()
    expect((screen.getByText('Save') as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getAllByText('Remove bracket')[1])
    fireEvent.click(screen.getByText('Add target'))
    expect(screen.getByText('Every target needs an item name.')).toBeTruthy()
  })

  it('resets to the defaults when customised', async () => {
    const fetchMock = stubFetch()
    await openEditor(true)

    fireEvent.click(screen.getByText('Reset to defaults'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/targets', expect.objectContaining({ method: 'DELETE' })),
    )
  })
})
