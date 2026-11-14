import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CharacterView, EquippedItem } from '../api'
import { CharacterSnapshot } from './CharacterSnapshot'

function item(slot: string, name: string): EquippedItem {
  return {
    slot,
    name,
    item_id: null,
    quality: 'UNCOMMON',
    quality_name: 'Uncommon',
    item_level: 20,
    armor_type: null,
    armor: null,
    stats: [],
    dps: null,
    icon_url: null,
  }
}

// Shaped like the real level 18 snapshot (tests/fixtures/forever_*.json).
const character: CharacterView = {
  name: 'Brumboldt',
  surname: 'Doomlet',
  level: 18,
  race: 'Gnome',
  character_class: 'Warrior',
  guild: 'Daves Discount Meats',
  equipped_item_level: 16.7,
  gear_slots_filled: 13,
  captured_at: '2026-11-13T17:22:00',
  stats: {
    health: 412,
    strength: 48,
    agility: 31,
    stamina: 44,
    intellect: 22,
    spirit: 27,
    attack_power: 96,
    armor: 812,
    defense: 95,
    dodge: 5.12,
    parry: 5,
    block: null,
    crit: 4.8,
  },
  professions: [
    { name: 'Engineering', skill: 104, max_skill: 150, primary: true },
    { name: 'Fishing', skill: null, max_skill: null, primary: false },
  ],
  specialization: null,
  equipment: [
    item('HEAD', 'Flying Tiger Goggles'),
    item('SHIRT', "Recruit's Shirt"),
    item('CHEST', 'Ironheart Chain'),
    item('AMMO', 'Crafted Heavy Shot'),
  ],
}

describe('CharacterSnapshot', () => {
  it('lists the gear worn, leaving out the shirt, tabard and ammo', () => {
    render(<CharacterSnapshot character={character} />)

    const equipped = screen.getByRole('heading', { name: 'Equipped' }).closest('section')!
    const rows = within(equipped)
      .getAllByRole('row')
      .map((row) => row.textContent)
    expect(rows).toEqual(['HeadFlying Tiger Gogglesilvl 20', 'ChestIronheart Chainilvl 20'])
  })

  it('shows stats, with percentages and unknowns', () => {
    render(<CharacterSnapshot character={character} />)

    const stats = screen.getByRole('heading', { name: 'Stats' }).closest('section')!
    const value = (label: string) => within(stats).getByText(label).nextElementSibling?.textContent
    expect(value('Health')).toBe('412')
    expect(value('Dodge')).toBe('5.1%')
    expect(value('Parry')).toBe('5.0%')
    expect(value('Block')).toBe('?')
    expect(value('Attack power')).toBe('96')
  })

  it('shows profession skill against its cap, or ? when unknown', () => {
    render(<CharacterSnapshot character={character} />)

    const professions = screen.getByRole('heading', { name: 'Professions' }).closest('section')!
    const [engineering, fishing] = within(professions).getAllByRole('listitem')
    expect(engineering.textContent).toBe('Engineering104/150')
    const bar = within(engineering).getByRole('progressbar')
    expect([bar.getAttribute('value'), bar.getAttribute('max')]).toEqual(['104', '150'])
    expect(fishing.textContent).toBe('Fishing?')
  })

  it('leaves out panels it has no data for', () => {
    render(<CharacterSnapshot character={{ ...character, stats: null, professions: [], captured_at: null }} />)

    expect(screen.queryByRole('heading', { name: 'Stats' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Professions' })).toBeNull()
    expect(screen.queryByText('as of the last sync', { exact: false })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Equipped' })).toBeTruthy()
  })
})
