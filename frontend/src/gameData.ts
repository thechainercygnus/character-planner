import type { GameItem } from './api'

/** Helpers for the addon's game data (#185). */

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
]

/** "2 days ago", "10 minutes ago", "just now". */
export function ago(when: Date, now: number = Date.now()): string {
  const seconds = Math.round((now - when.getTime()) / 1000)
  const format = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return format.format(-Math.round(seconds / size), unit)
  }
  return 'just now'
}

/** Backend times are ISO 8601; ones without an offset are UTC. */
export function parseTime(iso: string): Date {
  return new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
}

/** One entry per item id, counts added up across stacks and bags. */
export function stacked(items: GameItem[]): GameItem[] {
  const byId = new Map<number, GameItem>()
  for (const item of items) {
    const seen = byId.get(item.item_id)
    byId.set(item.item_id, seen ? { ...seen, count: seen.count + item.count } : item)
  }
  return [...byId.values()].sort((a, b) => b.quality - a.quality || a.item_id - b.item_id)
}
