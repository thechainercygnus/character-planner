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
    level: null,
    pinned: false,
    item_id: null,
    item_level: null,
    armor_type: null,
    armor: null,
    stats: {},
    ...overrides,
  }
}

const targets: GearTargets = {
  targets: [
    target('WAIST', 'Old Belt', { level: 15 }),
    target('BACK', 'Old Cape', { item_id: 7, armor: 20, level: 15 }),
    target('BACK', 'New Cape', { level: 20 }),
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
  await screen.findByLabelText('Back target 1 item')
}

function savedBody(fetchMock: ReturnType<typeof stubFetch>): GearTargets {
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  return JSON.parse(String(put[1]!.body)) as GearTargets
}

describe('TargetsEditor', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reorders within a slot, removes and adds targets, keeping hand-entered fields', async () => {
    const fetchMock = stubFetch()
    await openEditor()

    fireEvent.click(screen.getByRole('button', { name: 'Move Back target 2 up' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Waist target 1' }))
    fireEvent.change(screen.getByLabelText('Slot for a new target'), { target: { value: 'NECK' } })
    fireEvent.click(screen.getByText('Add target'))
    fireEvent.change(screen.getByLabelText('Neck target 1 item'), { target: { value: 'Locket' } })
    fireEvent.change(screen.getByLabelText('Neck target 1 level'), { target: { value: '22' } })
    fireEvent.change(screen.getByLabelText('Back target 1 level'), { target: { value: '' } })
    fireEvent.click(screen.getByLabelText('Neck target 1 pinned'))
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/targets', expect.objectContaining({ method: 'PUT' })))
    expect(savedBody(fetchMock).targets.map((t) => [t.slot, t.item, t.item_id, t.armor, t.level, t.pinned])).toEqual([
      ['BACK', 'New Cape', null, null, null, false],
      ['BACK', 'Old Cape', 7, 20, 15, false],
      ['NECK', 'Locket', null, null, 22, true],
    ])
  })

  it('fills the item id and source from the pool by name, and shows its level', async () => {
    const fetchMock = stubFetch()
    await openEditor()

    fireEvent.click(screen.getByText('Add waist target'))
    fireEvent.change(screen.getByLabelText('Waist target 2 item'), { target: { value: 'kindlegem girdle' } })
    expect((screen.getByLabelText('Waist target 2 source') as HTMLInputElement).value).toBe('Hall of Thanes – Plunder')
    expect((screen.getByLabelText('Waist target 2 level') as HTMLInputElement).placeholder).toBe(
      String(girdle.effective_level ?? 'auto'),
    )
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/targets', expect.objectContaining({ method: 'PUT' })))
    expect(savedBody(fetchMock).targets[3].item_id).toBe(girdle.item_id)
  })

  it('blocks bad levels and blank names', async () => {
    stubFetch()
    await openEditor()

    fireEvent.change(screen.getByLabelText('Back target 1 level'), { target: { value: '81' } })
    expect(screen.getByText('Levels must be whole numbers from 1 to 80, or blank.')).toBeTruthy()
    expect((screen.getByText('Save') as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText('Back target 1 level'), { target: { value: '15' } })
    fireEvent.click(screen.getByText('Add back target'))
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
