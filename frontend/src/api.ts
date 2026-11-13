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
  /** Seconds; weapons only. */
  attack_speed?: number | null
  enchantments?: Enchantment[]
  icon_url: string | null
}

/** An enchant on an equipped item (views.py Enchantment). */
export interface Enchantment {
  /** As the game shows it: "Enchanted: Scope (+1 Damage)". */
  text: string
  enchantment_id: number | null
  source_item: string | null
  source_item_id: number | null
  /** PERMANENT; temporary kinds not seen yet. */
  kind: string | null
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
  /** The tree it's in (Protection, Arms...). */
  tree?: string | null
}

/** Points in one tree. Blizzard lists only trees with points in them. */
export interface TreePoints {
  name: string
  spent_points: number | null
}

export interface Specialization {
  /** The tree with the most points. */
  name: string
  /** In every tree. */
  spent_points: number | null
  trees?: TreePoints[]
  talents: Talent[]
}

export interface CharacterView {
  name: string | null
  surname: string | null
  level: number | null
  race: string | null
  character_class: string | null
  guild: string | null
  /** Average item level of the gear worn, computed by the backend (the API's counts empty slots). */
  equipped_item_level: number | null
  gear_slots_filled: number
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
  /** Not before this level (ADR 0015); the item's own level wins when higher or this is null. */
  level: number | null
  /** Pinned with Make target: always listed on the Upgrades tab until worn (ADR 0014). */
  pinned: boolean
  item_id: number | null
  item_level: number | null
  armor_type: string | null
  armor: number | null
  stats: Record<string, number>
}

/** Gear targets, one list (ADR 0015): edited in the app, or gear_targets.yaml (ADR 0014). Within a slot, list order is priority. */
export interface GearTargets {
  targets: GearTarget[]
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
  /** The level the target counts from: planned, or the item's own when higher. */
  level: number | null
  /** The slot's next targets above the character's level, nearest first. */
  upcoming: UpcomingTarget[]
}

/** A target above the character's level, shown early so you can prepare for it. */
export interface UpcomingTarget {
  target: GearTarget
  target_info: TargetInfo | null
  level: number | null
  /** Against what's worn now; null without stat data. */
  score_delta: number | null
}

/** A slot whose targets are all above the character's level. */
export interface SlotOutlook {
  slot: string
  equipped: EquippedItem | null
  upcoming: UpcomingTarget[]
}

export interface Attribution {
  name: string
  url: string
  text: string
}

export interface CreditLink {
  name: string
  url: string
}

/** The page footer (#43): data credits, the source link (AGPL) and the version. */
export interface About {
  version: string
  source_url: string
  data: CreditLink & { sources: CreditLink[] }
}

export interface GearPlan {
  level: number | null
  /** Per slot, the target to go for now (ADR 0015). */
  rows: GearRow[]
  /** Slots with nothing to go for yet. */
  later: SlotOutlook[]
  attributions: Attribution[]
  /** Targets edited in the app rather than gear_targets.yaml. */
  targets_customised: boolean
}

/** Guest mode (ADR 0017): classes with rules and the shipped weight presets. */
/** A class guest mode offers, with its shipped weight presets (the first is default). */
export interface GuestClass {
  key: string
  name: string
  presets: { key: string; name: string }[]
}

export interface GuestOptions {
  classes: GuestClass[]
  factions: string[]
}

export interface GuestQuery {
  classKey: string
  level: number
  faction: string
  preset: string
}

export interface Status {
  character: string
  namespace: string
  /** Syncs use the app's own token (#107): this says the Battle.net client is set. */
  can_sync: boolean
  /** The last sync's answer: false after a 404 (wrong name or region), null before one. */
  character_found: boolean | null
  /** The optional Battle.net login; syncs don't need it. */
  logged_in: boolean
  token_expires_at: number | null
  latest_snapshots: Record<string, string>
  /** Refreshes running now, from any process: "pool", "enchants" (#87). */
  refreshing: string[]
}

export type SyncResult = Record<string, number>

/** A stat weight preset (scoring.py PresetSummary, ADR 0013). */
export interface PresetSummary {
  key: string
  name: string
  /** From the curated files: can be reset, not renamed or deleted. */
  shipped: boolean
  /** A shipped preset with edits saved in the app. */
  customised: boolean
}

/** The active preset's weights, its defaults and every preset. */
/** What the character can wear and how Upgrades lists items: recommend.yaml or edits (ADR 0016). */
export interface UsageRules {
  weapon_types: string[]
  armor_types: string[]
  /** Plate counts from this level; null never. */
  plate_from_level: number | null
  /** Mail from this level (Hunters, Shamans); null never. */
  mail_from_level: number | null
  two_handers: boolean
  /** Which weapon types count as two-handers; null any. */
  two_hand_types: string[] | null
  off_hand_types: string[]
  /** Weapons in the off hand count from this level (Dual Wield); null: from the start. */
  dual_wield_from_level: number | null
  /** Include items this many levels above yours. */
  levels_ahead: number
  per_slot: number
  /** Score gains at or below this aren't listed. */
  min_gain: number
}

export interface RulesView {
  rules: UsageRules
  defaults: UsageRules
  customised: boolean
  weapon_type_options: string[]
  armor_type_options: string[]
  off_hand_type_options: string[]
  two_hand_type_options: string[]
}

/** Notifications (#12, ADR 0021). */
export type AlertKind =
  | 'level_up'
  | 'target_reached'
  | 'target_in_reach'
  | 'new_upgrade'
  | 'job_failed'
  | 'upstream_errors'
export type Audience = 'user' | 'system'

export interface AlertInfo {
  kind: AlertKind
  audience: Audience
  label: string
}

export interface Destination {
  id: number
  name: string
  kind: string
  audience: Audience
  /** Masked: the webhook's token is never sent back. */
  url: string
  alerts: AlertKind[]
  enabled: boolean
  last_sent_at: string | null
  last_error: string | null
}

export interface RecentAlert {
  destination: string
  kind: AlertKind
  created_at: string
  sent_at: string | null
  failed: boolean
  attempts: number
  last_error: string | null
}

export interface NotificationsView {
  destinations: Destination[]
  alerts: AlertInfo[]
  recent: RecentAlert[]
  /** System alerts go to user destinations while no system destination exists. */
  system_alerts_to_user: boolean
}

export interface SendResult {
  ok: boolean
  status: number | null
  error: string | null
  retry_after: number | null
  gone: boolean
}

export interface WeightsView {
  weights: Record<string, number>
  /** What Reset restores; equal to weights for a preset of your own. */
  defaults: Record<string, number>
  customised: boolean
  /** Active preset key. */
  preset: string
  presets: PresetSummary[]
}

export interface RefreshResult {
  found: string[]
  missing: string[]
  errors: string[]
  icons: number
  companion_fetched: number
  companion_not_found: number[]
}

export interface PoolSource {
  kind: 'drop' | 'quest' | 'rare' | 'crafted'
  /** Null for a rare or a crafted item. */
  dungeon_id: string | null
  dungeon: string | null
  /** The dungeon's level range, or the rare's. */
  min_level: number | null
  max_level: number | null
  /** The boss for a drop, the quest for a reward. */
  detail: string | null
  choice: boolean
  quest_min_level: number | null
  /** The reward's quest, described (#7). */
  quest: QuestStep | null
  /** Quests to do first, earliest first; each step's quests are done side by side (#7). */
  chain: QuestStep[][]
  /** A rare's drop (#6): the rare, its zone, how many spawn points, whether elite. */
  rare_id: string | null
  rare: string | null
  zone: string | null
  spawns: number | null
  elite: boolean
  /** Crafted from a recipe the character knows (#10): the profession and recipe. */
  profession: string | null
  recipe: string | null
}

/** One quest in a chain (quests.py QuestStep). Only the name is always known. */
export interface QuestStep {
  quest_id: number | null
  name: string
  level: number | null
  /** Level needed to pick it up. */
  min_level: number | null
  giver: string | null
  /** Where the giver is (dungeon quests). */
  location: string | null
  /** The quest's zone (elite quests). */
  zone: string | null
  /** The dungeon it's done in (dungeon quests). */
  dungeon: string | null
  wowhead: string | null
  /** Described by Forever Companion, not just named. */
  known: boolean
}

/** Pool items for the character's level window (pool.py PoolView). */
export interface PoolView {
  level: number | null
  faction: string | null
  window: [number, number] | null
  items: PoolItem[]
}

/** A dungeon drop or quest reward from the item pool (pool.py). */
export interface PoolItem {
  item_id: number
  name: string
  slot: string | null
  quality: Quality | null
  sources: PoolSource[]
  item_slot: string | null
  weapon_type: string | null
  item_level: number | null
  required_level: number | null
  /** Required level, or for items without one the quest pickup / dungeon minimum level. */
  effective_level: number | null
  armor_type: string | null
  armor: number | null
  stats: Record<string, number>
  dps: number | null
  icon_url: string | null
  wowhead: string | null
}

export interface Candidate {
  item: PoolItem
  score_gain: number
  item_level_delta: number | null
  armor_delta: number | null
  stat_deltas: Record<string, number>
  /** False when the item needs a few more levels. */
  usable_now: boolean
  /** One of the gear targets. */
  is_target: boolean
  /** A pinned target: listed even when it isn't a top pick. */
  pinned: boolean
}

export type ChoiceKind = 'dismissed'

/** An item dismissed on the Upgrades tab (choices.py ItemChoiceView). */
export interface ItemChoice {
  item_id: number
  name: string
  choice: ChoiceKind
  created_at: string
}

export interface SlotRecommendation {
  slot: string
  equipped: EquippedItem | null
  candidates: Candidate[]
}

export interface DungeonUpgrade {
  slot: string
  item: PoolItem
  score_gain: number
  /** How this dungeon gives it: a boss drop or a quest. */
  source: PoolSource
}

export interface DungeonValue {
  dungeon_id: string
  dungeon: string
  min_level: number | null
  max_level: number | null
  total_gain: number
  /** Biggest gain first. */
  upgrades: DungeonUpgrade[]
}

export interface Recommendations {
  level: number | null
  window: [number, number] | null
  rows: SlotRecommendation[]
  dungeons: DungeonValue[]
  considered: number
  unscored: number
  attributions: Attribution[]
}

export interface PoolRefresh {
  dungeons_listed: number
  dungeons_fetched: number
  pool_size: number
  in_window: number
  items_fetched: number
  items_not_found: number[]
  /** Quest chain steps looked up by id (#7). */
  quests_fetched: number
  /** Rares in the latest GET /rares, merged into the stored ones (#6). */
  rares_listed: number
  /** Class quests in the latest GET /class-quests, merged into the stored ones (#8). */
  class_quests_listed: number
  errors: string[]
}

/** One sync (progress.py). Timestamps are UTC without an offset. */
export interface ProgressPoint {
  captured_at: string
  level: number | null
  item_level: number | null
  /** Sum of the equipped items' scores with the current stat weights. */
  gear_score: number | null
  health: number | null
  armor: number | null
  stamina: number | null
}

export interface GearChange {
  captured_at: string
  slot: string
  before: string | null
  after: string | null
  item_level_before: number | null
  item_level_after: number | null
  score_change: number
}

export interface LevelUp {
  captured_at: string
  level: number
}

export interface Progress {
  points: ProgressPoint[]
  gear_changes: GearChange[]
  level_ups: LevelUp[]
}

export interface PlanStep {
  talent: string
  rank: number
  /** The talent's id in Blizzard's trees (#88); filled in from the name for older plans. */
  talent_id?: number | null
}

/** One talent in a tree (#88): its place on the grid, ranks and prerequisites. */
export interface TalentNode {
  node_id: number
  talent_id: number
  name: string
  spell_id: number | null
  /** 1 at the top. */
  row: number
  /** 1 at the left of its tree. */
  col: number
  max_rank: number
  /** Each rank's description. */
  ranks: string[]
  /** Talent ids that must be at their max rank first. */
  requires: number[]
  icon_url: string | null
}

export interface SpecTree {
  spec_id: number
  name: string
  nodes: TalentNode[]
}

export interface ClassTree {
  class_name: string
  tree_id: number
  specs: SpecTree[]
}

export interface TalentTreeView {
  class_name: string | null
  /** Null until the trees are loaded (after the first sync, in the background). */
  tree: ClassTree | null
  loading: boolean
}

export interface TalentPlan {
  spec: string
  steps: PlanStep[]
}

export interface StepStatus {
  talent: string
  talent_id: number | null
  /** Target rank after this step. */
  rank: number
  /** Points this step adds. */
  points: number
  current: number
  state: 'done' | 'partial' | 'pending'
  first_point: number
  /** Level at which this step's last point can be spent. */
  level: number
}

/** The talent plan compared with the synced talents (talents.py, ADR 0009). */
export interface TalentPlanView {
  /** The plan as stored, for editing. */
  plan: TalentPlan
  spec: string
  current_spec: string | null
  level: number | null
  available: number | null
  spent: number | null
  planned_points: number
  steps: StepStatus[]
  next: { talent: string; talent_id: number | null; rank: number; level: number } | null
  off_plan: { talent: string; talent_id: number | null; current: number; planned: number }[]
  customised: boolean
}

/** POST /api/enchants/refresh (enchants.py). */
export interface RecipeRefresh {
  professions: string[]
  recipes_listed: number
  recipes_fetched: number
  items_fetched: number
  items_not_found: number[]
  errors: string[]
}

/** An enchant recipe from the catalog (enchants.py EnchantOption). */
export interface EnchantOption {
  recipe_id: number
  name: string
  /** Enchanting, Engineering, Leatherworking, Blacksmithing. */
  profession: string
  category: string
  slots: string[]
  two_handed: boolean
  shield_only: boolean
  /** The in-game description, when the recipe has one. */
  text: string | null
  /** Stat name -> value; "Weapon Damage" is flat damage per hit. */
  effects: Record<string, number>
  effects_source: 'description' | 'curated' | 'equipped' | null
  temporary: boolean
  crafted_item_id: number | null
  season_of_discovery: boolean
  /** From the reagents' material levels; an estimate. */
  estimated_level: number | null
}

export interface CurrentEnchant {
  text: string
  effects: Record<string, number>
  score: number
}

export interface EnchantPick {
  option: EnchantOption
  score: number
  /** Over the enchant on now, or over nothing. */
  score_gain: number
  /** False when the estimated level is a few levels away. */
  usable_now: boolean
  /** The character knows the recipe. */
  can_make: boolean
}

export interface SlotEnchants {
  slot: string
  /** Equipped item name; null when the slot is empty. */
  item: string | null
  current: CurrentEnchant | null
  /** Biggest gain first. */
  picks: EnchantPick[]
  /** An enchant is on and something better is in reach. */
  current_is_weaker: boolean
}

/** GET /api/enchants/recommendations (enchants.py, ADR 0010). */
export interface EnchantAdvice {
  level: number | null
  /** Catalog size; 0 until enchant data is refreshed. */
  recipes: number
  rows: SlotEnchants[]
  considered: number
  /** In reach but nothing to weigh: procs, or scopes and kits without known effects. */
  unscored: number
  /** No level estimate, so left out. */
  unknown_level: number
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export type LookAheadKind = 'dungeon' | 'target' | 'talent' | 'class_quest' | 'profession'

/** One thing a coming level brings (lookahead.py LookAheadEvent, #4). */
export interface LookAheadEvent {
  kind: LookAheadKind
  title: string
  detail: string | null
  /** An essential class quest. */
  essential: boolean
  /** A pinned gear target. */
  pinned: boolean
  /** A dungeon not open yet in Forever. */
  locked: boolean
  link: string | null
}

export interface LookAhead {
  level: number | null
  /** How far ahead, as asked. */
  levels: number
  /** Each coming level with something on it, in order. */
  groups: { level: number; events: LookAheadEvent[] }[]
}

/** A trainer rank not reached yet (crafting.py NextRank, #10). */
export interface NextRank {
  name: string
  max_skill: number
  train_at_skill: number
  train_at_level: number
  skill_ready: boolean
  level_ready: boolean
}

export interface ProfessionRow {
  name: string
  primary: boolean
  skill: number | null
  max_skill: number | null
  /** From the skill cap: Journeyman for 150. */
  rank: string | null
  next_rank: NextRank | null
  /** How a rank is earned when it isn't a trainer. */
  note: string | null
  known_recipes: number
  /** Equippable items its known recipes make. */
  crafted_gear: string[]
}

export interface ProfessionsView {
  level: number | null
  professions: ProfessionRow[]
}

export type ClassQuestStatus = 'done' | 'missed' | 'now' | 'soon' | 'later'

/** A quest that unlocks class abilities (class_quests.py ClassQuestRow, #8). */
export interface ClassQuestRow {
  id: string
  class_key: string
  level: number
  name: string
  faction: string
  /** Only these races ("night-elf"); null for any. */
  races: string[] | null
  giver: string | null
  location: string | null
  reward: string | null
  /** Unlocks a core ability. */
  essential: boolean
  done: boolean
  /** missed: essential, at or below the character's level and not done. */
  status: ClassQuestStatus
}

export interface ClassQuestChecklist {
  class_name: string | null
  level: number | null
  /** How many levels ahead "coming soon" looks. */
  soon_levels: number
  /** Class quests stored for any class: 0 before the first data refresh. */
  listed: number
  /** By level, then name. */
  rows: ClassQuestRow[]
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
  about: () => request<About>('/api/about'),
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
  rules: () => request<RulesView>('/api/rules'),
  saveRules: (rules: UsageRules) =>
    request<RulesView>('/api/rules', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rules),
    }),
  resetRules: () => request<RulesView>('/api/rules', { method: 'DELETE' }),
  notifications: () => request<NotificationsView>('/api/notifications'),
  addDestination: (body: { name: string; url: string; audience: Audience }) =>
    request<NotificationsView>('/api/notifications/destinations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateDestination: ({
    id,
    ...change
  }: {
    id: number
    name?: string
    url?: string
    alerts?: AlertKind[]
    enabled?: boolean
  }) =>
    request<NotificationsView>(`/api/notifications/destinations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(change),
    }),
  removeDestination: (id: number) =>
    request<NotificationsView>(`/api/notifications/destinations/${id}`, { method: 'DELETE' }),
  testDestination: (id: number) =>
    request<SendResult>(`/api/notifications/destinations/${id}/test`, { method: 'POST' }),
  activatePreset: (key: string) =>
    request<WeightsView>('/api/weights/active', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }),
  createPreset: ({ name, weights }: { name: string; weights: Record<string, number> }) =>
    request<WeightsView>('/api/weights/presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, weights }),
    }),
  renamePreset: ({ key, name }: { key: string; name: string }) =>
    request<WeightsView>(`/api/weights/presets/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  deletePreset: (key: string) =>
    request<WeightsView>(`/api/weights/presets/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  recommendations: () => request<Recommendations>('/api/recommendations'),
  guest: () => request<GuestOptions>('/api/guest'),
  guestRecommendations: ({ classKey, level, faction, preset }: GuestQuery) =>
    request<Recommendations>(
      `/api/guest/recommendations?${new URLSearchParams({ class: classKey, level: String(level), faction, preset })}`,
    ),
  choices: () => request<ItemChoice[]>('/api/choices'),
  setChoice: ({ itemId, name, choice }: { itemId: number; name: string; choice: ChoiceKind }) =>
    request<ItemChoice[]>(`/api/choices/${itemId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choice, name }),
    }),
  pool: () => request<PoolView>('/api/pool'),
  professions: () => request<ProfessionsView>('/api/professions'),
  lookAhead: (levels: number) => request<LookAhead>(`/api/look-ahead?levels=${levels}`),
  classQuests: () => request<ClassQuestChecklist>('/api/class-quests'),
  setClassQuestDone: ({ id, done }: { id: string; done: boolean }) =>
    request<ClassQuestChecklist>(`/api/class-quests/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ done }),
    }),
  targets: () => request<GearTargets>('/api/targets'),
  saveTargets: (targets: GearTargets) =>
    request<GearTargets>('/api/targets', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(targets),
    }),
  resetTargets: () => request<GearTargets>('/api/targets', { method: 'DELETE' }),
  pinTarget: ({ itemId, slot }: { itemId: number; slot: string }) =>
    request<GearTargets>('/api/targets/pins', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, slot }),
    }),
  unpinTarget: (itemId: number) => request<GearTargets>(`/api/targets/pins/${itemId}`, { method: 'DELETE' }),
  clearChoice: (itemId: number) => request<ItemChoice[]>(`/api/choices/${itemId}`, { method: 'DELETE' }),
  progress: () => request<Progress>('/api/progress'),
  talents: () => request<TalentPlanView>('/api/talents'),
  saveTalentPlan: (plan: TalentPlan) =>
    request<TalentPlanView>('/api/talents/plan', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plan),
    }),
  resetTalentPlan: () => request<TalentPlanView>('/api/talents/plan', { method: 'DELETE' }),
  talentTree: () => request<TalentTreeView>('/api/talents/tree'),
  /** With a level, only that level's window (guest mode, #48); else the character's. */
  refreshPool: (level?: number) =>
    request<PoolRefresh>(level ? `/api/pool/refresh?level=${level}` : '/api/pool/refresh', { method: 'POST' }),
  refreshEnchants: () => request<RecipeRefresh>('/api/enchants/refresh', { method: 'POST' }),
  enchants: () => request<EnchantAdvice>('/api/enchants/recommendations'),
}

/** Backend timestamps are UTC without an offset; mark them as UTC before parsing. */
export function parseUtc(timestamp: string): Date {
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(timestamp) ? timestamp : `${timestamp}Z`)
}

/** Battle.net slot types (MAIN_HAND) as people read them (Main Hand). */
/** Battle.net equipment slots in display order (recommend.py EQUIPMENT_SLOTS). */
export const EQUIPMENT_SLOTS = [
  'HEAD',
  'NECK',
  'SHOULDER',
  'BACK',
  'CHEST',
  'WRIST',
  'HANDS',
  'WAIST',
  'LEGS',
  'FEET',
  'FINGER_1',
  'FINGER_2',
  'TRINKET_1',
  'TRINKET_2',
  'MAIN_HAND',
  'OFF_HAND',
  'RANGED',
] as const

export function slotLabel(slot: string): string {
  return slot
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
