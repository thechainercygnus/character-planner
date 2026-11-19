import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameDataView } from '../api'
import { ago, parseTime, stacked } from '../gameData'
import { GameDataPanel, ImportGameDataDialog, QuestLog } from './GameData'

const NOW = Date.parse('2026-11-18T12:00:00Z')
const HOURS_AGO = (hours: number) => new Date(NOW - hours * 3_600_000).toISOString()

// The fixtures are dated from NOW: the clock is pinned there, or their ages drift with the
// real date ("2 hours ago" becomes "yesterday"). Only Date: timers stay real for findBy.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})
afterEach(() => {
  vi.useRealTimers()
})

const empty: GameDataView = {
  imported: false,
  uploaded_at: null,
  captured_at: null,
  addon_version: null,
  captured: null,
  data: null,
  items: {},
}

const imported: GameDataView = {
  imported: true,
  uploaded_at: HOURS_AGO(1),
  captured_at: HOURS_AGO(2),
  addon_version: '0.1.0',
  captured: { bags: HOURS_AGO(2), bank: null, quests: HOURS_AGO(2) },
  data: {
    schema_version: 1,
    addon_version: '0.1.0',
    captured_at: 0,
    character: { name: 'Brumboldt', surname: 'Doomlet', level: 25, region: 'US', realm: '91' },
    bags: {
      captured_at: 0,
      items: [
        { container: 0, slot: 1, item_id: 270230, count: 1, quality: 2 },
        { container: 0, slot: 2, item_id: 2589, count: 20, quality: 1 },
        { container: 1, slot: 1, item_id: 2589, count: 7, quality: 1 },
      ],
    },
    bank: null,
    quests: {
      captured_at: 0,
      completed: [],
      log: [
        {
          quest_id: 1640,
          title: 'The Summoning',
          complete: false,
          objectives: [
            { text: 'Summon and defeat Bartleby', type: 'monster', done: 0, needed: 1, finished: false },
            { text: 'Bartleby the Drunk', type: 'item', done: 1, needed: 1, finished: true },
            // As the game writes most objectives: the count is in the text (a real file, #185).
            { text: '3/10 Redridge Brute slain', type: 'monster', done: 3, needed: 10, finished: false },
          ],
        },
      ],
    },
  },
  items: {
    '270230': {
      name: 'Kindlegem Girdle',
      quality: 'UNCOMMON',
      icon_url: 'https://wow.zamimg.com/images/wow/icons/medium/inv_belt_01.jpg',
      wowhead: 'https://www.wowhead.com/forever/item=270230',
    },
    '2589': { name: null, quality: 'COMMON', icon_url: null, wowhead: 'https://www.wowhead.com/forever/item=2589' },
  },
}

function serve(view: GameDataView, ui: ReactNode, answers: Partial<Record<string, Response>> = {}) {
  const calls: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ?? null })
      return answers[`${method} ${url}`] ?? Response.json(view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  return { calls, container }
}

describe('game data helpers', () => {
  it('says how long ago, in words', () => {
    expect(ago(new Date(NOW - 2 * 86_400_000), NOW)).toBe('2 days ago')
    expect(ago(new Date(NOW - 3 * 3_600_000), NOW)).toBe('3 hours ago')
    expect(ago(new Date(NOW - 10 * 60_000), NOW)).toBe('10 minutes ago')
    expect(ago(new Date(NOW - 5_000), NOW)).toBe('just now')
  })

  it('reads times without an offset as UTC', () => {
    expect(parseTime('2026-11-18T12:00:00').getTime()).toBe(NOW)
    expect(parseTime('2026-11-18T12:00:00+00:00').getTime()).toBe(NOW)
    expect(parseTime('2026-11-18T12:00:00Z').getTime()).toBe(NOW)
  })

  it('adds up stacks of the same item, best quality first', () => {
    const items = stacked(imported.data!.bags!.items)
    expect(items.map((item) => [item.item_id, item.count])).toEqual([
      [270230, 1],
      [2589, 27],
    ])
  })
})

describe('GameDataPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('offers the import before there is any', async () => {
    serve(empty, <GameDataPanel battleNetLevel={25} levelSource={null} />)
    expect(await screen.findByText(/which Battle.net can't see/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Import game data' })).toBeTruthy()
  })

  it('shows the bags as items, with links, counts and their age', async () => {
    serve(imported, <GameDataPanel battleNetLevel={25} levelSource={null} />)
    const bags = await screen.findByRole('region', { name: 'Bags' })
    const girdle = within(bags).getByRole('link', { name: 'Kindlegem Girdle' })
    expect(girdle.getAttribute('href')).toBe('https://www.wowhead.com/forever/item=270230')
    // No catalog names it yet: its id, still linked.
    expect(within(bags).getByRole('link', { name: 'Item 2589' })).toBeTruthy()
    expect(within(bags).getByText('×27')).toBeTruthy()
    expect(within(bags).getByText(/From the game, .* ago/)).toBeTruthy()
  })

  it('marks the bank as not seen yet, not empty', async () => {
    serve(imported, <GameDataPanel battleNetLevel={25} levelSource={null} />)
    const bank = await screen.findByRole('region', { name: 'Bank' })
    expect(within(bank).getByText(/Not seen yet: open your bank/)).toBeTruthy()
  })

  it("says the planner uses the game's level when it's newer than the sync (ADR 0052)", async () => {
    const level = { level: 25, source: 'game' as const, at: HOURS_AGO(2) }
    serve(imported, <GameDataPanel battleNetLevel={24} levelSource={level} />)
    expect(
      await screen.findByText(/Battle.net says 24, as of an older sync: the planner uses the game's level/),
    ).toBeTruthy()
  })

  it("says the planner uses Battle.net's level when the sync is newer", async () => {
    const level = { level: 24, source: 'battle.net' as const, at: HOURS_AGO(1) }
    serve(imported, <GameDataPanel battleNetLevel={24} levelSource={level} />)
    // The file says 25, but an older capture can't outvote the sync.
    expect(await screen.findByText(/Battle.net says 24, as of a newer sync: the planner uses that/)).toBeTruthy()
  })
})

describe('ImportGameDataDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uploads the picked file as it is, and shows what it held', async () => {
    const { calls, container } = serve(empty, <ImportGameDataDialog />, {
      'POST /api/game-data': Response.json(imported),
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Import game data' }))
    expect(screen.getByText(/CharacterPlannerExport\.lua$/, { selector: 'code' })).toBeTruthy()
    const file = new File(['CharacterPlannerExportDB = {}'], 'CharacterPlannerExport.lua')
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
    expect(await screen.findByText(/Imported/)).toBeTruthy()
    const post = calls.find((call) => call.method === 'POST')!
    expect(post.body).toBe(file)
    expect(screen.getByText('Bags: 3 items')).toBeTruthy()
    expect(screen.getByText('Bank: not seen yet')).toBeTruthy()
    expect(screen.getByText('Quest log: 1 quest')).toBeTruthy()
  })

  it('shows why a file was refused', async () => {
    const { container } = serve(empty, <ImportGameDataDialog />, {
      'POST /api/game-data': Response.json(
        { detail: "This file is Lilalx's, not Brumboldt Doomlet's: pick Lilalx" },
        { status: 422 },
      ),
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Import game data' }))
    const file = new File(['x'], 'CharacterPlannerExport.lua')
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
    expect((await screen.findByRole('alert')).textContent).toBe(
      "This file is Lilalx's, not Brumboldt Doomlet's: pick Lilalx",
    )
  })

  it('deletes the import after asking', async () => {
    vi.stubGlobal('confirm', () => true)
    const { calls } = serve(imported, <ImportGameDataDialog />, { 'DELETE /api/game-data': Response.json(empty) })
    fireEvent.click(await screen.findByRole('button', { name: 'Import game data' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Delete imported data' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true))
  })
})

describe('QuestLog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows each quest's objectives with their counts", async () => {
    serve(imported, <QuestLog />)
    const quest = await screen.findByRole('link', { name: 'The Summoning' })
    expect(quest.getAttribute('href')).toBe('https://www.wowhead.com/forever/quest=1640')
    expect(screen.getByText('0/1')).toBeTruthy()
    expect(screen.getByText('1/1')).toBeTruthy()
    expect(screen.getAllByLabelText('done')).toHaveLength(1)
    // A count the text already has isn't shown twice.
    const brutes = screen.getByText(/Redridge Brute slain/)
    expect(brutes.textContent).toBe('3/10 Redridge Brute slain ')
    expect(screen.queryByText('3/10')).toBeNull()
  })

  it('points to the import when there is none', async () => {
    serve(empty, <QuestLog />)
    expect(await screen.findByText(/comes from the CharacterPlannerExport addon/)).toBeTruthy()
  })
})
