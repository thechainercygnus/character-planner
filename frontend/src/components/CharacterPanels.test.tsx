import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CharacterView } from '../api'
import { CharacterHeader } from './CharacterPanels'

const synced: CharacterView = {
  name: 'Brumboldt',
  surname: 'Doomlet',
  level: 18,
  race: 'Gnome',
  character_class: 'Warrior',
  guild: null,
  equipped_item_level: null,
  gear_slots_filled: 0,
  captured_at: '2026-11-13T05:29:06Z',
  level_source: { level: 18, source: 'battle.net', at: '2026-11-13T05:29:06Z' },
  stats: null,
  professions: [],
  specialization: null,
  equipment: [],
}

describe('CharacterHeader', () => {
  it("shows the last sync's level with no label", () => {
    render(<CharacterHeader character={synced} />)
    expect(screen.getByText(/Level 18/)).toBeTruthy()
    expect(screen.queryByText('(from the game)')).toBeNull()
  })

  it("shows the game's level, labelled, when its data is newer (ADR 0052)", () => {
    const at = new Date(Date.now() - 10 * 60_000).toISOString()
    render(<CharacterHeader character={{ ...synced, level_source: { level: 22, source: 'game', at } }} />)
    expect(screen.getByText(/Level 22/)).toBeTruthy()
    const label = screen.getByText('(from the game)')
    expect(label.getAttribute('title')).toBe(
      'From the game, 10 minutes ago: newer than the last sync (Battle.net says 18)',
    )
  })
})
