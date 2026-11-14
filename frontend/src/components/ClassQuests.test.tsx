import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClassQuestChecklist, ClassQuestRow } from '../api'
import { APP_HEADER } from '../api'
import { ClassQuests } from './ClassQuests'

function row(overrides: Partial<ClassQuestRow>): ClassQuestRow {
  return {
    id: 'q',
    class_key: 'warrior',
    level: 10,
    name: 'Quest',
    faction: 'both',
    races: null,
    giver: null,
    location: null,
    reward: null,
    essential: false,
    done: false,
    status: 'later',
    ...overrides,
  }
}

// A level 18 Gnome Warrior's quests, from the real GET /class-quests response.
const muren = row({
  id: 'warrior-defensive-stance-dwarf',
  name: 'Muren Stormpike',
  level: 10,
  faction: 'alliance',
  races: ['dwarf', 'gnome'],
  giver: 'Muren Stormpike',
  location: 'Dun Morogh',
  reward: 'Defensive Stance, Taunt, Sunder Armor and a weapon',
  essential: true,
  status: 'missed',
})
const yorus = row({
  id: 'warrior-fire-hardened',
  name: 'Yorus Barleybrew',
  level: 20,
  giver: 'Yorus Barleybrew',
  reward: 'Fire Hardened armor pieces',
  status: 'soon',
})
const islander = row({
  id: 'warrior-berserker-stance',
  name: 'The Islander → Whirlwind Weapon',
  level: 30,
  essential: true,
  status: 'later',
})
const checklist: ClassQuestChecklist = {
  class_name: 'Warrior',
  level: 18,
  soon_levels: 5,
  listed: 44,
  rows: [muren, yorus, islander],
}

function renderChecklist(data: ClassQuestChecklist = checklist) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ClassQuests data={data} />
    </QueryClientProvider>,
  )
}

describe('ClassQuests', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('groups quests by status and flags a missed essential one', () => {
    renderChecklist()

    expect(screen.getByText('1 essential quest at or below your level not done yet.', { exact: false })).toBeTruthy()
    const missed = screen.getByRole('list', { name: 'Missed' })
    expect(within(missed).getByText('Muren Stormpike', { selector: 'strong' })).toBeTruthy()
    expect(within(missed).getByText('essential').className).toBe('tag warn')
    expect(within(missed).getByText('Defensive Stance, Taunt, Sunder Armor and a weapon')).toBeTruthy()
    expect(within(missed).getByText('Muren Stormpike, Dun Morogh')).toBeTruthy()
    expect(within(screen.getByRole('list', { name: 'Coming soon' })).getByText('Yorus Barleybrew', { selector: 'strong' })).toBeTruthy()
    expect(within(screen.getByRole('list', { name: 'Later' })).getByText('essential').className).toBe('tag')
    expect(screen.queryByRole('list', { name: 'Available now' })).toBeNull()
    expect(screen.queryByRole('list', { name: 'Done' })).toBeNull()
  })

  it('marks a quest done and shows the saved checklist', async () => {
    const saved: ClassQuestChecklist = { ...checklist, rows: [{ ...muren, done: true, status: 'done' }, yorus, islander] }
    const fetchMock = vi.fn(async () => Response.json(saved))
    vi.stubGlobal('fetch', fetchMock)
    renderChecklist()

    fireEvent.click(within(screen.getByRole('list', { name: 'Missed' })).getByRole('checkbox'))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledWith('/api/class-quests/warrior-defensive-stance-dwarf', {
      method: 'PUT',
      headers: { ...APP_HEADER, 'Content-Type': 'application/json' },
      body: JSON.stringify({ done: true }),
    })
  })

  it('explains an empty checklist', () => {
    renderChecklist({ ...checklist, listed: 0, rows: [] })
    expect(screen.getByText('No class quests loaded yet', { exact: false })).toBeTruthy()
  })
})
