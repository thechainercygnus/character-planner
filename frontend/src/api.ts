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
  armor_type: string | null
  armor: number | null
  stats: ItemStat[]
  dps: number | null
  icon_url: string | null
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
  item_id: number | null
  item_level: number | null
  armor_type: string | null
  armor: number | null
  stats: Record<string, number>
}

export type SourceName = 'blizzard' | 'companion' | 'manual'

/** What's known about a target item, merged from Blizzard, Forever Companion and gear_targets.yaml. */
export interface TargetInfo {
  sources: SourceName[]
  item_id: number | null
  item_level: number | null
  required_level: number | null
  quality: Quality | null
  armor_type: string | null
  armor: number | null
  stats: ItemStat[]
  dps: number | null
  icon_url: string | null
  drops: string[]
  rewards: string[]
  verified: number | null
  wowhead: string | null
  conflicts: string[]
}

export type Verdict = 'reached' | 'upgrade' | 'sidegrade' | 'downgrade' | 'unknown'

export interface GearRow {
  slot: string
  equipped: EquippedItem | null
  target: GearTarget
  target_info: TargetInfo | null
  reached: boolean
  verdict: Verdict
  item_level_delta: number | null
  armor_delta: number | null
  stat_deltas: Record<string, number>
  /** Weighted score of the target minus the equipped item; null without stat data. */
  score_delta: number | null
  verdict_basis: 'score' | 'item_level' | 'none'
  warning: string | null
}

export interface Attribution {
  name: string
  url: string
  text: string
}

export interface GearPlan {
  level: number | null
  bracket_min_level: number | null
  next_bracket_level: number | null
  next_bracket_size: number
  rows: GearRow[]
  attributions: Attribution[]
}

export interface Status {
  character: string
  namespace: string
  logged_in: boolean
  token_expires_at: number | null
  latest_snapshots: Record<string, string>
}

export type SyncResult = Record<string, number>

export interface WeightsView {
  weights: Record<string, number>
  defaults: Record<string, number>
  customised: boolean
}

export interface RefreshResult {
  found: string[]
  missing: string[]
  errors: string[]
  icons: number
  companion_fetched: number
  companion_not_found: number[]
}

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
  refreshItems: () => request<RefreshResult>('/api/items/refresh?force=true', { method: 'POST' }),
  weights: () => request<WeightsView>('/api/weights'),
  saveWeights: (weights: Record<string, number>) =>
    request<WeightsView>('/api/weights', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ weights }),
    }),
  resetWeights: () => request<WeightsView>('/api/weights', { method: 'DELETE' }),
}

/** Battle.net slot types (MAIN_HAND) as people read them (Main Hand). */
export function slotLabel(slot: string): string {
  return slot
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
