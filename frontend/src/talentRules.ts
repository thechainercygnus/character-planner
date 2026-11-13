import type { ClassTree, PlanStep, SpecTree, TalentNode } from './api'

/**
 * Talent plan rules in the browser (#88), the same as the server's check_plan: ranks rise
 * one talent at a time up to its max, a prerequisite is maxed first, and a row opens after
 * POINTS_PER_ROW points in its tree. Used to refuse a click before it breaks the plan; the
 * server checks again when the plan is saved.
 */
export const POINTS_PER_ROW = 5

export type NodeIndex = Map<number, { spec: SpecTree; node: TalentNode }>

export function indexTree(tree: ClassTree): NodeIndex {
  const index: NodeIndex = new Map()
  for (const spec of tree.specs) for (const node of spec.nodes) index.set(node.talent_id, { spec, node })
  return index
}

/** Each talent's planned rank, and the points planned in each tree. */
export function planTotals(steps: PlanStep[]): { ranks: Map<number, number>; total: number } {
  const ranks = new Map<number, number>()
  let total = 0
  for (const step of steps) {
    if (step.talent_id == null) continue
    const before = ranks.get(step.talent_id) ?? 0
    if (step.rank > before) {
      total += step.rank - before
      ranks.set(step.talent_id, step.rank)
    }
  }
  return { ranks, total }
}

export function pointsPerTree(steps: PlanStep[], index: NodeIndex): Map<number, number> {
  const spent = new Map<number, number>()
  for (const [talentId, rank] of planTotals(steps).ranks) {
    const found = index.get(talentId)
    if (found) spent.set(found.spec.spec_id, (spent.get(found.spec.spec_id) ?? 0) + rank)
  }
  return spent
}

/** The first problem with a plan, in spending order, or null. */
export function firstProblem(steps: PlanStep[], index: NodeIndex): string | null {
  const ranks = new Map<number, number>()
  const spent = new Map<number, number>()
  for (const [i, step] of steps.entries()) {
    const found = step.talent_id == null ? undefined : index.get(step.talent_id)
    if (!found) return `Step ${i + 1}: ${step.talent} isn't in these trees`
    const { spec, node } = found
    const before = ranks.get(node.talent_id) ?? 0
    if (step.rank <= before) return `Step ${i + 1}: ${node.name} is already at rank ${before}`
    if (step.rank > node.max_rank) return `Step ${i + 1}: ${node.name} only has ${node.max_rank} ranks`
    if (before === 0) {
      const needed = POINTS_PER_ROW * (node.row - 1)
      if ((spent.get(spec.spec_id) ?? 0) < needed) return `${node.name} needs ${needed} points in ${spec.name} first`
      for (const required of node.requires) {
        const prereq = index.get(required)?.node
        if (prereq && (ranks.get(required) ?? 0) < prereq.max_rank)
          return `${node.name} needs ${prereq.name} at ${prereq.max_rank}/${prereq.max_rank} first`
      }
    }
    spent.set(spec.spec_id, (spent.get(spec.spec_id) ?? 0) + step.rank - before)
    ranks.set(node.talent_id, step.rank)
  }
  return null
}

/** The plan with one more point in this talent, at the end of the order. */
export function addPoint(steps: PlanStep[], node: TalentNode): PlanStep[] {
  const rank = (planTotals(steps).ranks.get(node.talent_id) ?? 0) + 1
  const last = steps.at(-1)
  // A point straight after another in the same talent extends that step.
  if (last && last.talent_id === node.talent_id) return [...steps.slice(0, -1), { ...last, rank }]
  return [...steps, { talent: node.name, talent_id: node.talent_id, rank }]
}

/** The plan with this talent's last point taken out. */
export function removePoint(steps: PlanStep[], talentId: number): PlanStep[] {
  const at = steps.findLastIndex((step) => step.talent_id === talentId)
  if (at === -1) return steps
  const earlier = steps.slice(0, at).filter((s) => s.talent_id === talentId)
  const before = Math.max(0, ...earlier.map((s) => s.rank))
  const step = steps[at]
  if (step.rank - 1 <= before) return steps.filter((_, i) => i !== at)
  return steps.map((s, i) => (i === at ? { ...s, rank: s.rank - 1 } : s))
}

/** The level each planned point is spent at: the first comes at 10, then one a level. */
export function levelForPoint(point: number): number {
  return 9 + point
}
