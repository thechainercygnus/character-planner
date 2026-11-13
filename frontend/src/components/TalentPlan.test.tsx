import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TalentPlanView } from '../api'
import { TalentPlanPanel } from './TalentPlan'

const view: TalentPlanView = {
  plan: {
    spec: 'Protection',
    steps: [
      { talent: 'Shield Specialization', rank: 5 },
      { talent: 'Deflection', rank: 2 },
    ],
  },
  spec: 'Protection',
  current_spec: 'Protection',
  level: 18,
  available: 9,
  spent: 9,
  planned_points: 7,
  steps: [
    {
      talent: 'Shield Specialization',
      talent_id: 135507,
      rank: 5,
      points: 5,
      current: 5,
      state: 'done',
      first_point: 1,
      level: 14,
    },
    {
      talent: 'Deflection',
      talent_id: null,
      rank: 2,
      points: 2,
      current: 0,
      state: 'pending',
      first_point: 6,
      level: 16,
    },
  ],
  next: { talent: 'Deflection', talent_id: null, rank: 1, level: 15 },
  off_plan: [{ talent: 'Improved Revenge', talent_id: 135500, current: 3, planned: 0 }],
  customised: false,
}

function renderPanel(data: TalentPlanView = view) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TalentPlanPanel view={data} />
    </QueryClientProvider>,
  )
}

describe('TalentPlanPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the next point, steps and points off plan', () => {
    renderPanel()

    expect(screen.getByText('9/9 points · plan 7 points in Protection')).toBeTruthy()
    expect(screen.getByText('Deflection', { selector: 'strong' })).toBeTruthy()
    expect(screen.getByText('available now')).toBeTruthy()
    expect(screen.getByText('(not in the plan)')).toBeTruthy()
    expect(screen.getByText('5/5')).toBeTruthy()
    expect(screen.getByText('0/2 · by level 16')).toBeTruthy()
  })

  it('says when the plan is used up', () => {
    renderPanel({ ...view, next: null, off_plan: [] })
    expect(screen.getByText("Every planned point is spent. Extend the plan to see what's next.")).toBeTruthy()
  })

  it('flags unspent points and a different spec', () => {
    renderPanel({ ...view, spent: 7, current_spec: 'Arms' })
    expect(screen.getByText('2 unspent points.')).toBeTruthy()
    expect(screen.getByText('Your points are mostly in Arms, but the plan is for Protection.')).toBeTruthy()
  })

  it('edits the plan as text while the talent trees are not loaded', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) =>
      url === '/api/talents/tree'
        ? Response.json({ class_name: 'Warrior', tree: null, loading: false })
        : Response.json({ ...view, plan: JSON.parse(String(init?.body)), customised: true }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: 'Edit plan' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add step' }))
    fireEvent.change(screen.getByLabelText('Step 3 talent'), { target: { value: 'Anticipation' } })
    fireEvent.change(screen.getByLabelText('Step 3 rank'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Move step 3 up' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/talents/plan', expect.objectContaining({ method: 'PUT' })),
    )
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
    const body = JSON.parse(String(put[1]?.body))
    expect(body.steps).toEqual([
      { talent: 'Shield Specialization', rank: 5 },
      { talent: 'Anticipation', rank: 5 },
      { talent: 'Deflection', rank: 2 },
    ])
  })

  it('asks for the trees again until their icons have loaded', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const node = {
      node_id: 10,
      talent_id: 1,
      name: 'Shield Specialization',
      spell_id: 7,
      row: 1,
      col: 1,
      max_rank: 5,
      ranks: ['a', 'b', 'c', 'd', 'e'],
      requires: [],
    }
    const tree = (icon: string | null, loading: boolean) => ({
      class_name: 'Warrior',
      tree: { class_name: 'Warrior', tree_id: 1117, specs: [{ spec_id: 257, name: 'Protection', nodes: [{ ...node, icon_url: icon }] }] },
      loading,
    })
    const responses = [tree(null, true), tree('https://icons/shield.jpg', false)]
    const fetchMock = vi.fn(async () => Response.json(responses.shift() ?? tree('https://icons/shield.jpg', false)))
    vi.stubGlobal('fetch', fetchMock)
    try {
      const { container } = renderPanel()
      await waitFor(() => expect(screen.getByRole('region', { name: 'Protection tree' })).toBeTruthy())
      expect(container.querySelector('.talent-node img')).toBeNull()
      await vi.advanceTimersByTimeAsync(5_000)
      await waitFor(() => expect(container.querySelector('.talent-node img')).not.toBeNull())
      // Loaded: no more asking.
      const calls = fetchMock.mock.calls.length
      await vi.advanceTimersByTimeAsync(20_000)
      expect(fetchMock.mock.calls.length).toBe(calls)
    } finally {
      vi.useRealTimers()
    }
  })

  it('blocks saving an incomplete step', () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Edit plan' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add step' }))

    expect(screen.getByText('Every step needs a talent and a rank from 1 to 10.')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
