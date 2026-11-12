import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PresetSummary, WeightsView } from '../api'
import { WeightsDialog } from './WeightsDialog'

const defaults = { Stamina: 1, Armor: 0.1 }
const shipped: PresetSummary[] = [
  { key: 'leveling-tank', name: 'Leveling tank', shipped: true, customised: false },
  { key: 'solo-dps', name: 'Solo DPS', shipped: true, customised: false },
]
const view: WeightsView = { weights: defaults, defaults, customised: false, preset: 'leveling-tank', presets: shipped }
const mine: WeightsView = {
  ...view,
  preset: 'mine',
  presets: [...shipped, { key: 'mine', name: 'Mine', shipped: false, customised: false }],
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <WeightsDialog />
    </QueryClientProvider>,
  )
}

async function openDialog() {
  const trigger = await screen.findByRole('button', { name: /^Stat weights/ })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(trigger)
  return screen.getByRole('dialog') as HTMLDialogElement
}

function input(name: string) {
  return screen.getByText(name).parentElement!.querySelector('input')!
}

describe('WeightsDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('opens as a modal from the button', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(view)))
    renderDialog()

    const dialog = await openDialog()
    expect(dialog.open).toBe(true)
  })

  it('applies edited weights with a PUT and marks the button customised', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { weights: Record<string, number> }
        return Response.json({ ...view, weights: body.weights, customised: true })
      }
      return Response.json(view)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()
    await openDialog()

    fireEvent.change(input('Stamina'), { target: { value: '2' } })
    expect(screen.getByText('default 1')).toBeTruthy()

    fireEvent.click(screen.getByText('Apply'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/weights', expect.objectContaining({ method: 'PUT' })))
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
    expect(JSON.parse(String(put[1]!.body))).toEqual({ weights: { Stamina: 2, Armor: 0.1 } })
    expect(await screen.findByText('• customised')).toBeTruthy()
  })

  it('discards unapplied edits when closed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(view)))
    renderDialog()
    const dialog = await openDialog()

    fireEvent.change(input('Stamina'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(dialog.open).toBe(false)

    await openDialog()
    expect(input('Stamina').value).toBe('1')
  })

  it('blocks applying values outside -10..10', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(view)))
    renderDialog()
    await openDialog()

    fireEvent.change(input('Armor'), { target: { value: '50' } })

    expect(screen.getByText('Weights must be numbers from -10 to 10.')).toBeTruthy()
    expect((screen.getByText('Apply') as HTMLButtonElement).disabled).toBe(true)
  })

  it('names the active preset on the button and switches presets', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
      Response.json(init?.method === 'PUT' && url === '/api/weights/active' ? { ...view, preset: 'solo-dps' } : view),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    expect(await screen.findByRole('button', { name: 'Stat weights: Leveling tank' })).toBeTruthy()
    await openDialog()
    fireEvent.change(screen.getByLabelText('Preset'), { target: { value: 'solo-dps' } })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/weights/active', expect.objectContaining({ method: 'PUT' })),
    )
    const put = fetchMock.mock.calls.find(([url]) => url === '/api/weights/active')!
    expect(JSON.parse(String(put[1]!.body))).toEqual({ key: 'solo-dps' })
    expect(await screen.findByRole('button', { name: 'Stat weights: Solo DPS' })).toBeTruthy()
    // Shipped presets can be reset but not renamed or deleted.
    expect(screen.getByText('Reset to defaults')).toBeTruthy()
    expect(screen.queryByText('Rename…')).toBeNull()
  })

  it('saves the edited weights as a new preset', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json(init?.method === 'POST' ? mine : view),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()
    await openDialog()

    fireEvent.change(input('Stamina'), { target: { value: '0.5' } })
    fireEvent.click(screen.getByText('Save as…'))
    fireEvent.change(screen.getByLabelText('Name for the new preset'), { target: { value: 'Mine' } })
    fireEvent.click(screen.getByText('Save preset'))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/weights/presets', expect.objectContaining({ method: 'POST' })),
    )
    const post = fetchMock.mock.calls.find(([url]) => url === '/api/weights/presets')!
    expect(JSON.parse(String(post[1]!.body))).toEqual({ name: 'Mine', weights: { Stamina: 0.5, Armor: 0.1 } })
    expect(await screen.findByRole('button', { name: 'Stat weights: Mine' })).toBeTruthy()
    // Your own preset: rename and delete, nothing to reset to.
    expect(screen.getByText('Rename…')).toBeTruthy()
    expect(screen.queryByText('Reset to defaults')).toBeNull()
  })

  it('renames and deletes a preset of your own', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json(init?.method === 'DELETE' ? view : mine),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))
    renderDialog()
    await openDialog()

    fireEvent.click(await screen.findByText('Rename…'))
    expect((screen.getByLabelText('New name') as HTMLInputElement).value).toBe('Mine')
    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Questing' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/weights/presets/mine', expect.objectContaining({ method: 'PATCH' })),
    )

    fireEvent.click(screen.getByText('Delete'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/weights/presets/mine', expect.objectContaining({ method: 'DELETE' })),
    )
    expect(await screen.findByRole('button', { name: 'Stat weights: Leveling tank' })).toBeTruthy()
  })
})
