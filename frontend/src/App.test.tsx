import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CharacterView, TalentPlanView } from './api'
import App from './App'
import { recommendations } from './test/fixtures'

const character: CharacterView = {
  name: 'Brumboldt',
  surname: 'Doomlet',
  level: 19,
  race: 'Gnome',
  character_class: 'Warrior',
  guild: null,
  equipped_item_level: 16.7,
  gear_slots_filled: 13,
  captured_at: '2026-11-13T05:29:06Z',
  stats: null,
  professions: [],
  specialization: {
    name: 'Protection',
    spent_points: 13,
    trees: [
      { name: 'Arms', spent_points: 4 },
      { name: 'Protection', spent_points: 9 },
    ],
    talents: [
      { name: 'Improved Heroic Strike', rank: 3, description: null, tree: 'Arms' },
      { name: 'Deflection', rank: 1, description: null, tree: 'Arms' },
      { name: 'Shield Specialization', rank: 5, description: null, tree: 'Protection' },
      { name: 'Improved Revenge', rank: 3, description: null, tree: 'Protection' },
    ],
  },
  equipment: [],
}

const talents: TalentPlanView = {
  plan: { spec: 'Protection', steps: [{ talent: 'Shield Specialization', rank: 5 }] },
  spec: 'Protection',
  current_spec: 'Protection',
  level: 19,
  available: 10,
  spent: 13,
  planned_points: 5,
  steps: [
    {
      talent: 'Shield Specialization',
      talent_id: null,
      rank: 5,
      points: 5,
      current: 5,
      state: 'done',
      first_point: 1,
      level: 14,
    },
  ],
  next: null,
  off_plan: [],
  customised: false,
}

const RESPONSES: Record<string, unknown> = {
  '/api/character': character,
  '/api/recommendations': recommendations,
  '/api/talents': talents,
  '/api/talents/tree': { class_name: 'Warrior', tree: null, loading: false },
}

function renderAt(hash: string) {
  window.location.hash = hash
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url in RESPONSES ? Response.json(RESPONSES[url]) : Response.json({ detail: 'not in this test' }, { status: 404 }),
    ),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

describe('App tabs (#41)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.location.hash = ''
  })

  it('orders the tabs Upgrades, Dungeons, Plan, Talents, Progress, Character', async () => {
    renderAt('')
    const tabs = await screen.findAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent?.replace(/\d+$/, '').trim())).toEqual([
      'Upgrades',
      'Dungeons',
      'Plan',
      'Talents',
      'Progress',
      'Character',
    ])
  })

  it('#talents opens the talent plan, with its editor', async () => {
    renderAt('#talents')
    expect(await screen.findByText('Every planned point is spent. Extend the plan to see what\'s next.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Edit plan' })).toBeTruthy()
  })

  it('#character shows the snapshot: talents as spent, per tree, with nothing to edit', async () => {
    renderAt('#character')
    const spent = await screen.findByRole('region', { name: 'Talents' })
    expect(within(spent).getByRole('heading', { level: 2 }).textContent).toBe('Talents Arms 4 · Protection 9')
    expect(within(spent).getByText('Improved Heroic Strike').closest('div')?.querySelector('h3')?.textContent).toBe(
      'Arms',
    )
    expect(screen.getByText(/^From Blizzard's Battle.net API, as of the last sync/)).toBeTruthy()
    // Read-only: no plan, no editors.
    expect(screen.queryByRole('button', { name: 'Edit plan' })).toBeNull()
    expect(screen.queryByText(/planned/)).toBeNull()
  })
})
