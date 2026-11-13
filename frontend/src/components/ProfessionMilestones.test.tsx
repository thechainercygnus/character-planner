import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ProfessionRow, ProfessionsView } from '../api'
import { ProfessionMilestones } from './ProfessionMilestones'

// From the real professions snapshot (level 18): Engineering 104 of 150, Cooking 87 of 150.
const engineering: ProfessionRow = {
  name: 'Engineering',
  primary: true,
  skill: 104,
  max_skill: 150,
  rank: 'Journeyman',
  next_rank: {
    name: 'Expert',
    max_skill: 225,
    train_at_skill: 125,
    train_at_level: 20,
    skill_ready: false,
    level_ready: false,
  },
  note: null,
  known_recipes: 19,
  crafted_gear: ['Flying Tiger Goggles', 'Rough Boomstick'],
}
const cooking: ProfessionRow = {
  ...engineering,
  name: 'Cooking',
  primary: false,
  skill: 87,
  note: 'Expert comes from a book; Artisan from a quest in Tanaris.',
  known_recipes: 11,
  crafted_gear: [],
}

describe('ProfessionMilestones', () => {
  it('shows skill against the cap, what the next rank needs and the gear crafted', () => {
    render(<ProfessionMilestones data={{ level: 18, professions: [engineering, cooking] }} />)

    const row = screen.getByRole('listitem', { name: 'Engineering' })
    expect(within(row).getByText('104 / 150')).toBeTruthy()
    expect(within(row).getByText('Journeyman', { exact: false })).toBeTruthy()
    const bar = within(row).getByRole('progressbar', { name: 'Engineering skill' })
    expect([bar.getAttribute('value'), bar.getAttribute('max')]).toEqual(['104', '150'])
    expect(
      within(row).getByText('Expert (cap 225) at 125 skill (21 to go) and level 20 (2 to go).'),
    ).toBeTruthy()
    expect(within(row).getByText('Crafts gear: Flying Tiger Goggles, Rough Boomstick')).toBeTruthy()

    const cookingRow = screen.getByRole('listitem', { name: 'Cooking' })
    expect(within(cookingRow).getByText('Tanaris', { exact: false })).toBeTruthy()
    expect(within(cookingRow).queryByText('Crafts gear', { exact: false })).toBeNull()
  })

  it('says when the next rank can be trained, and when the last is reached', () => {
    const ready: ProfessionRow = {
      ...engineering,
      skill: 130,
      next_rank: { ...engineering.next_rank!, skill_ready: true, level_ready: true },
    }
    const artisan: ProfessionRow = { ...engineering, name: 'Mining', rank: 'Artisan', max_skill: 300, next_rank: null }
    render(<ProfessionMilestones data={{ level: 20, professions: [ready, artisan] }} />)
    expect(screen.getByText('Expert (cap 225) can be trained now.').className).toBe('ok')
    expect(screen.getByText('Last rank reached.')).toBeTruthy()
  })

  it('shows nothing before a sync', () => {
    const empty: ProfessionsView = { level: null, professions: [] }
    const { container } = render(<ProfessionMilestones data={empty} />)
    expect(container.innerHTML).toBe('')
  })
})
