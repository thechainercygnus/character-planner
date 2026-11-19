import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BuildsView } from '../api'
import { BuildPicker } from './BuildPicker'

const view: BuildsView = {
  class_name: 'Warrior',
  builds: [
    {
      key: 'protection-dungeon',
      name: 'Protection: dungeon tank',
      role: 'tank',
      preset: 'dungeon-tank',
      preset_name: 'Dungeon tank',
      talents: true,
      spec: 'Protection',
    },
    {
      key: 'arms-leveling',
      name: 'Arms: leveling',
      role: 'dps',
      preset: 'solo-dps',
      preset_name: 'Solo DPS',
      talents: true,
      spec: 'Arms',
    },
  ],
  current: 'protection-dungeon',
  customised: ['weights'],
}

type Call = { url: string; method: string; body: unknown; as: string | null }

function show(as?: number) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : null,
        as: headers['X-Character-Id'] ?? null,
      })
      if (init?.method === 'PUT') return Response.json({ ...view, current: 'arms-leveling', customised: [] })
      return Response.json(view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <BuildPicker label="Build" {...(as === undefined ? {} : { as })} />
    </QueryClientProvider>,
  )
  return calls
}

describe('BuildPicker', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the build followed, what it sets, and what was changed since', async () => {
    show()
    const select = (await screen.findByRole('combobox', { name: 'Build' })) as HTMLSelectElement
    expect(select.value).toBe('protection-dungeon')
    expect(screen.getByText(/tank · Dungeon tank weights · Protection talents/)).toBeTruthy()
    expect(screen.getByText(/Customised since: stat weights\./)).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('follows another build, warning that its talents replace the plan', async () => {
    const calls = show(7)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Build' }), { target: { value: 'arms-leveling' } })
    expect(screen.getByText(/Its talent order replaces the talent plan/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Follow this build' }))
    await waitFor(() =>
      expect(calls).toContainEqual({ url: '/api/build', method: 'PUT', body: { key: 'arms-leveling' }, as: '7' }),
    )
    expect(calls[0]?.as).toBe('7') // the row's character, not the selected one
  })

  it('stops following one', async () => {
    const calls = show()
    fireEvent.change(await screen.findByRole('combobox', { name: 'Build' }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Stop following it' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ key: null }))
  })
})
