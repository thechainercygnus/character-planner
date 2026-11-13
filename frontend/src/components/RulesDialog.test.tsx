import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RulesView, UsageRules } from '../api'
import { RulesDialog } from './RulesDialog'

const rules: UsageRules = {
  weapon_types: ['Axe', 'Sword', 'Shield'],
  armor_types: ['cloth', 'leather', 'mail'],
  plate_from_level: 40,
  mail_from_level: null,
  two_handers: false,
  two_hand_types: null,
  off_hand_types: ['Shield'],
  levels_ahead: 3,
  per_slot: 3,
  min_gain: 1,
}
const view: RulesView = {
  rules,
  defaults: rules,
  customised: false,
  weapon_type_options: ['Axe', 'Sword', 'Wand', 'Shield'],
  armor_type_options: ['cloth', 'leather', 'mail'],
  off_hand_type_options: ['Shield', 'Miscellaneous'],
  two_hand_type_options: ['Axe', 'Staff', 'Sword'],
}

function stubFetch(current: RulesView = view) {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      return Response.json({ ...current, rules: JSON.parse(String(init.body)) as UsageRules, customised: true })
    }
    if (init?.method === 'DELETE') return Response.json(view)
    return Response.json(current)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function openDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RulesDialog />
    </QueryClientProvider>,
  )
  const trigger = await screen.findByRole('button', { name: /^Upgrades settings/ })
  await waitFor(() => expect((trigger as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(trigger)
}

function putBody(fetchMock: ReturnType<typeof stubFetch>): UsageRules {
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  return JSON.parse(String(put[1]!.body)) as UsageRules
}

describe('RulesDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('saves edited types and numbers', async () => {
    const fetchMock = stubFetch()
    await openDialog()

    fireEvent.click(screen.getByLabelText('Wand'))
    fireEvent.click(screen.getByLabelText('Sword'))
    fireEvent.click(screen.getByLabelText('Held in off-hand'))
    fireEvent.click(screen.getByLabelText('Two-handed weapons'))
    fireEvent.change(screen.getByLabelText('Plate from level'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Upgrades per slot'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Minimum score gain'), { target: { value: '2.5' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/rules', expect.objectContaining({ method: 'PUT' })))
    expect(putBody(fetchMock)).toEqual({
      ...rules,
      weapon_types: ['Axe', 'Shield', 'Wand'],
      off_hand_types: ['Shield', 'Miscellaneous'],
      two_handers: true,
      plate_from_level: null,
      per_slot: 5,
      min_gain: 2.5,
    })
    expect(await screen.findByText(/• customised/)).toBeTruthy()
  })

  it('saves a mail level and which two-handers count', async () => {
    const fetchMock = stubFetch()
    await openDialog()

    expect(screen.queryByText('Two-handed weapon types')).toBeNull()
    fireEvent.click(screen.getByLabelText('Two-handed weapons'))
    // Any type to begin with; unticking one narrows it.
    const twoHanders = within(screen.getByRole('group', { name: 'Two-handed weapon types' }))
    expect((twoHanders.getByLabelText('Sword') as HTMLInputElement).checked).toBe(true)
    fireEvent.click(twoHanders.getByLabelText('Sword'))
    fireEvent.click(twoHanders.getByLabelText('Axe'))
    fireEvent.change(screen.getByLabelText('Mail from level'), { target: { value: '40' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/rules', expect.objectContaining({ method: 'PUT' })))
    const saved = putBody(fetchMock)
    expect(saved.two_handers).toBe(true)
    expect(saved.mail_from_level).toBe(40)
    expect(saved.two_hand_types).toEqual(['Staff'])
  })

  it('blocks numbers out of range', async () => {
    stubFetch()
    await openDialog()

    fireEvent.change(screen.getByLabelText('Upgrades per slot'), { target: { value: '0' } })
    expect(screen.getByText('Upgrades per slot must be a whole number from 1 to 10.')).toBeTruthy()
    expect((screen.getByText('Save') as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText('Upgrades per slot'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Plate from level'), { target: { value: '90' } })
    expect(screen.getByText('Plate level must be 1 to 80, or blank for never.')).toBeTruthy()
  })

  it('resets to the defaults when customised', async () => {
    const fetchMock = stubFetch({ ...view, customised: true, rules: { ...rules, per_slot: 5 } })
    await openDialog()

    fireEvent.click(screen.getByText('Reset to defaults'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/rules', expect.objectContaining({ method: 'DELETE' })),
    )
  })
})
