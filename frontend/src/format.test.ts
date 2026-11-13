import { describe, expect, it } from 'vitest'
import { sourceText } from './format'
import { deadminesQuest, hallDrop } from './test/fixtures'

describe('sourceText', () => {
  it('names a drop by dungeon and boss, a quest by quest and dungeon', () => {
    expect(sourceText(hallDrop)).toBe('Hall of Thanes – Plunder')
    expect(sourceText(deadminesQuest)).toBe('Quest: The Defias Brotherhood (The Deadmines), choice')
  })

  it('names crafted gear by profession and recipe (#10)', () => {
    const crafted = {
      ...hallDrop,
      kind: 'crafted' as const,
      dungeon_id: null,
      dungeon: null,
      detail: null,
      profession: 'Engineering',
      recipe: 'Flying Tiger Goggles',
    }
    expect(sourceText(crafted)).toBe('Crafted: Engineering (Flying Tiger Goggles)')
  })

  it('names a rare with its zone, levels and spawn points (#6)', () => {
    // Humar the Pridelord and Swiftmane, from the real GET /rares response.
    const rare = {
      ...hallDrop,
      kind: 'rare' as const,
      dungeon_id: null,
      dungeon: null,
      detail: null,
      min_level: 10,
      max_level: 25,
      rare_id: 'humar',
      rare: 'Humar the Pridelord',
      zone: 'The Barrens',
      spawns: 1,
    }
    expect(sourceText(rare)).toBe('Rare: Humar the Pridelord, The Barrens (10–25), 1 spawn')
    expect(sourceText({ ...rare, rare: 'Swiftmane', spawns: 3 })).toBe('Rare: Swiftmane, The Barrens (10–25), 3 spawns')
    expect(sourceText({ ...rare, elite: true, min_level: 60, max_level: 60, spawns: 0 })).toBe(
      'Rare elite: Humar the Pridelord, The Barrens (60)',
    )
  })
})
