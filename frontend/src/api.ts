// Types mirror the backend's pydantic models in src/character_planner/views.py.
// Keep them in step when those change (later: generate them from /openapi.json).

export type Quality = 'POOR' | 'COMMON' | 'UNCOMMON' | 'RARE' | 'EPIC' | 'LEGENDARY'

export interface ItemStat {
  name: string
  value: number
}

export interface EquippedItem {
  slot: string
  name: string
  item_id: number | null
  quality: Quality | null
  quality_name: string | null
  item_level: number | null
  armor: number | null
  stats: ItemStat[]
}

export interface Stats {
  health: number | null
  strength: number | null
  agility: number | null
  stamina: number | null
  intellect: number | null
  spirit: number | null
  attack_power: number | null
  armor: number | null
  defense: number | null
  dodge: number | null
  parry: number | null
  block: number | null
  crit: number | null
}

export interface Profession {
  name: string
  skill: number | null
  max_skill: number | null
  primary: boolean
}

export interface Talent {
  name: string
  rank: number | null
  description: string | null
}

export interface Specialization {
  name: string
  spent_points: number | null
  talents: Talent[]
}

export interface CharacterView {
  name: string | null
  surname: string | null
  level: number | null
  race: string | null
  character_class: string | null
  guild: string | null
  equipped_item_level: number | null
  captured_at: string | null
  stats: Stats | null
  professions: Profession[]
  specialization: Specialization | null
  equipment: EquippedItem[]
}

export interface GearTarget {
  slot: string
  item: string
  source: string
  priority: number | null
}

export interface GearRow {
  slot: string
  equipped: EquippedItem | null
  target: GearTarget
  reached: boolean
}

export interface GearPlan {
  level: number | null
  bracket_min_level: number | null
  next_bracket_level: number | null
  next_bracket_size: number
  rows: GearRow[]
}

export interface Status {
  character: string
  namespace: string
  logged_in: boolean
  token_expires_at: number | null
  latest_snapshots: Record<string, string>
}

export type SyncResult = Record<string, number>

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body) detail = String(body.detail)
    } catch {
      // not JSON; keep statusText
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export const api = {
  status: () => request<Status>('/api/status'),
  character: () => request<CharacterView>('/api/character'),
  gear: () => request<GearPlan>('/api/gear'),
  sync: () => request<SyncResult>('/api/sync', { method: 'POST' }),
}

/** Battle.net slot types (MAIN_HAND) as people read them (Main Hand). */
export function slotLabel(slot: string): string {
  return slot
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
