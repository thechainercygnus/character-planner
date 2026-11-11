import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WeightsView } from '../api'
import { WeightsDialog } from './WeightsDialog'

const defaults = { Stamina: 1, Armor: 0.1 }
const view: WeightsView = { weights: defaults, defaults, customised: false }

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <WeightsDialog />
    </QueryClientProvider>,
  )
}

async function openDialog() {
  const trigger = await screen.findByRole('button', { name: 'Stat weights' })
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
        return Response.json({ weights: body.weights, defaults, customised: true })
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
})
