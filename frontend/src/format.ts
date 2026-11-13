import type { PoolItem, PoolSource, QuestStep } from './api'

// Display helpers shared by components. Kept out of component files so React's fast
// refresh still works for those (react/only-export-components).

export function signed(value: number, digits = 0): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

export function levelRange(min: number | null, max: number | null): string {
  if (min === null && max === null) return ''
  if (min === max || max === null) return `${min}`
  if (min === null) return `${max}`
  return `${min}–${max}`
}

export function sourceText(source: PoolSource): string {
  if (source.kind === 'quest') {
    return `Quest: ${source.detail ?? '?'} (${source.dungeon})${source.choice ? ', choice' : ''}`
  }
  return source.detail ? `${source.dungeon} – ${source.detail}` : source.dungeon
}

/** Who gives a quest and where, as far as Forever Companion knows: "Earthseer Farsen, Dun Morogh". */
export function questWhere(step: QuestStep): string {
  return [step.giver, step.location ?? step.dungeon ?? step.zone].filter(Boolean).join(', ')
}

/** The level a quest can be picked up at, when known. */
export function questLevel(step: QuestStep): number | null {
  return step.min_level ?? step.level
}

export function itemDetails(item: PoolItem): string {
  return [
    item.item_level !== null ? `ilvl ${item.item_level}` : null,
    item.weapon_type ?? item.armor_type,
    item.armor ? `${item.armor} armor` : null,
    item.dps ? `${item.dps} dps` : null,
    ...Object.entries(item.stats).map(([name, value]) => `+${value} ${name}`),
  ]
    .filter(Boolean)
    .join(' · ')
}
