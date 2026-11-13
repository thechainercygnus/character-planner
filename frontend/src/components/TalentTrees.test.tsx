import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClassTree, PlanStep, TalentNode, TalentPlanView } from '../api'
import { addPoint, firstProblem, indexTree, planTotals, removePoint } from '../talentRules'
import { TalentTrees } from './TalentTrees'

function node(talentId: number, name: string, row: number, col: number, maxRank: number, requires: number[] = []): TalentNode {
  return {
    node_id: talentId * 10,
    talent_id: talentId,
    name,
    spell_id: null,
    row,
    col,
    max_rank: maxRank,
    ranks: Array.from({ length: maxRank }, (_, i) => `${name} rank ${i + 1}`),
    requires,
    icon_url: null,
  }
}

// A small Protection-like tree: two row-1 talents, a row-2 talent, and one that needs
// Shield Specialization maxed.
const tree: ClassTree = {
  class_name: 'Warrior',
  tree_id: 1117,
  specs: [
    {
      spec_id: 257,
      name: 'Protection',
      nodes: [
        node(1, 'Shield Specialization', 1, 2, 5),
        node(2, 'Shield Wall', 1, 3, 1),
        node(3, 'Anticipation', 2, 1, 5),
        node(4, 'Master of Defense', 2, 2, 1, [1]),
      ],
    },
    { spec_id: 26, name: 'Arms', nodes: [node(5, 'Improved Heroic Strike', 1, 1, 3)] },
  ],
}
const index = indexTree(tree)

const step = (talentId: number, name: string, rank: number): PlanStep => ({ talent: name, talent_id: talentId, rank })

describe('talent rules', () => {
  it('adds points at the end of the order, extending a step in the same talent', () => {
    let plan = addPoint([], tree.specs[0].nodes[0])
    plan = addPoint(plan, tree.specs[0].nodes[0])
    expect(plan).toEqual([step(1, 'Shield Specialization', 2)])
    plan = addPoint(plan, tree.specs[0].nodes[1])
    expect(plan.map((s) => [s.talent_id, s.rank])).toEqual([
      [1, 2],
      [2, 1],
    ])
    expect(planTotals(plan).total).toBe(3)
  })

  it('opens a row after five points in its tree', () => {
    expect(firstProblem([step(3, 'Anticipation', 1)], index)).toBe(
      'Anticipation needs 5 points in Protection first',
    )
    expect(firstProblem([step(1, 'Shield Specialization', 5), step(3, 'Anticipation', 1)], index)).toBeNull()
    // Points in another tree don't count.
    expect(
      firstProblem([step(5, 'Improved Heroic Strike', 3), step(2, 'Shield Wall', 1), step(3, 'Anticipation', 1)], index),
    ).toMatch(/needs 5 points in Protection/)
  })

  it('needs a prerequisite maxed first', () => {
    const plan = [step(1, 'Shield Specialization', 4), step(2, 'Shield Wall', 1), step(4, 'Master of Defense', 1)]
    expect(firstProblem(plan, index)).toBe('Master of Defense needs Shield Specialization at 5/5 first')
  })

  it("takes a talent's last point off", () => {
    const plan = [step(1, 'Shield Specialization', 3), step(2, 'Shield Wall', 1), step(1, 'Shield Specialization', 5)]
    expect(removePoint(plan, 1)).toEqual([...plan.slice(0, 2), step(1, 'Shield Specialization', 4)])
    expect(removePoint(plan, 2)).toEqual([plan[0], plan[2]])
    expect(removePoint([step(1, 'Shield Specialization', 1)], 1)).toEqual([])
    expect(removePoint(plan, 99)).toBe(plan)
  })
})

const view: TalentPlanView = {
  plan: { spec: 'Protection', steps: [step(1, 'Shield Specialization', 2)] },
  spec: 'Protection',
  current_spec: 'Protection',
  level: 18,
  available: 9,
  spent: 3,
  planned_points: 2,
  steps: [
    { talent: 'Shield Specialization', talent_id: 1, rank: 2, points: 2, current: 2, state: 'done', first_point: 1, level: 11 },
  ],
  next: null,
  off_plan: [{ talent: 'Improved Heroic Strike', talent_id: 5, current: 1, planned: 0 }],
  customised: true,
}

function renderTrees() {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
    Response.json({ ...view, plan: JSON.parse(String(init?.body)) }),
  )
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TalentTrees tree={tree} view={view} />
    </QueryClientProvider>,
  )
  return fetchMock
}

const button = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name},`) })

describe('TalentTrees', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows each tree with the plan and what is spent in game', () => {
    renderTrees()
    expect(screen.getByRole('region', { name: 'Protection tree' })).toBeTruthy()
    expect(button('Shield Specialization').getAttribute('aria-label')).toBe(
      'Shield Specialization, planned 2 of 5, 2 spent',
    )
    // Off plan in game: shown on the tree all the same.
    expect(button('Improved Heroic Strike').getAttribute('aria-label')).toBe(
      'Improved Heroic Strike, planned 0 of 3, 1 spent',
    )
    expect(button('Anticipation').className).toContain('locked')
  })

  it('adds and removes points while editing, refuses ones that break the rules, and saves', async () => {
    const fetchMock = renderTrees()
    fireEvent.click(button('Shield Specialization'))
    expect(button('Shield Specialization').getAttribute('aria-label')).toContain('planned 2 of 5') // not editing yet

    fireEvent.click(screen.getByRole('button', { name: 'Edit plan' }))
    fireEvent.click(button('Anticipation'))
    expect(screen.getByRole('alert').textContent).toBe(
      "Can't add Anticipation: Anticipation needs 5 points in Protection first",
    )
    for (let i = 0; i < 3; i++) fireEvent.click(button('Shield Specialization'))
    fireEvent.click(button('Anticipation'))
    expect(button('Anticipation').getAttribute('aria-label')).toContain('planned 1 of 5')
    // Taking Shield Specialization below 5 would strand Anticipation.
    fireEvent.contextMenu(button('Shield Specialization'))
    expect(screen.getByRole('alert').textContent).toMatch(/^Can't take Shield Specialization off: Anticipation needs 5/)
    fireEvent.click(button('Anticipation'), { shiftKey: true })
    expect(button('Anticipation').getAttribute('aria-label')).toContain('planned 0 of 5')

    fireEvent.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/talents/plan', expect.objectContaining({ method: 'PUT' })),
    )
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body).toEqual({ spec: 'Protection', steps: [step(1, 'Shield Specialization', 5)] })
  })
})
