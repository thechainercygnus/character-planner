import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type MouseEvent } from 'react'
import { api, type ClassTree, type PlanStep, type TalentNode, type TalentPlanView } from '../api'
import { addPoint, firstProblem, indexTree, levelForPoint, planTotals, pointsPerTree, removePoint } from '../talentRules'

/** Each step with the points it adds and the levels they're spent at. */
function stepLevels(steps: PlanStep[]) {
  const pointsOf = steps.map((step, i) => {
    const earlier = steps.slice(0, i).filter((s) => s.talent_id === step.talent_id).map((s) => s.rank)
    return Math.max(0, step.rank - Math.max(0, ...earlier))
  })
  return steps.map((step, i) => {
    const before = pointsOf.slice(0, i).reduce((sum, n) => sum + n, 0)
    const last = before + pointsOf[i]
    return { step, points: pointsOf[i], from: levelForPoint(before + 1), to: levelForPoint(last) }
  })
}

/** Each talent's rank in game, from the plan view (planned talents and off-plan ones). */
function syncedRanks(view: TalentPlanView): Map<number, number> {
  const ranks = new Map<number, number>()
  for (const step of view.steps) if (step.talent_id != null) ranks.set(step.talent_id, step.current)
  for (const entry of view.off_plan) if (entry.talent_id != null) ranks.set(entry.talent_id, entry.current)
  return ranks
}

function tooltip(node: TalentNode, planned: number, spent: number): string {
  const lines = [`${node.name}: planned ${planned}/${node.max_rank}${spent ? `, ${spent} spent in game` : ''}`]
  if (planned > 0) lines.push(`Rank ${planned}: ${node.ranks[planned - 1]}`)
  if (planned < node.max_rank) lines.push(`Rank ${planned + 1}: ${node.ranks[planned]}`)
  return lines.join('\n')
}

function TalentButton({
  node,
  planned,
  spent,
  locked,
  editing,
  onAdd,
  onRemove,
}: {
  node: TalentNode
  planned: number
  spent: number
  locked: boolean
  editing: boolean
  onAdd: () => void
  onRemove: () => void
}) {
  const state = planned >= node.max_rank ? 'maxed' : planned > 0 ? 'partial' : locked ? 'locked' : 'open'
  return (
    <button
      type="button"
      className={`talent-node ${state}${spent > 0 ? ' spent' : ''}`}
      style={{ gridRow: node.row, gridColumn: node.col }}
      title={tooltip(node, planned, spent)}
      aria-label={`${node.name}, planned ${planned} of ${node.max_rank}${spent ? `, ${spent} spent` : ''}`}
      aria-disabled={!editing}
      onClick={(event: MouseEvent) => {
        if (!editing) return
        if (event.shiftKey) onRemove()
        else onAdd()
      }}
      onContextMenu={(event: MouseEvent) => {
        if (!editing) return
        event.preventDefault()
        onRemove()
      }}
    >
      {node.icon_url ? (
        <img src={node.icon_url} alt="" width={36} height={36} />
      ) : (
        <span className="talent-initials">{node.name.slice(0, 2)}</span>
      )}
      <span className="talent-rank">
        {planned}/{node.max_rank}
      </span>
      {spent > 0 && <span className="talent-spent">{spent}</span>}
    </button>
  )
}

/**
 * The class's talent trees with the plan and what's spent in game (#88). "Edit plan"
 * makes them clickable: click adds a point at the end of the order, right-click (or
 * shift-click) takes the talent's last point off. Clicks that would break the rules
 * (prerequisites, points per row) are refused with the reason; the server checks again.
 */
export function TalentTrees({ tree, view }: { tree: ClassTree; view: TalentPlanView }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<PlanStep[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const index = useMemo(() => indexTree(tree), [tree])
  const editing = draft !== null
  const steps = draft ?? view.plan.steps
  const { ranks: planned, total } = planTotals(steps)
  const perTree = pointsPerTree(steps, index)
  const synced = syncedRanks(view)

  const onSaved = (saved: TalentPlanView) => {
    queryClient.setQueryData(['talents'], saved)
    void queryClient.invalidateQueries({ queryKey: ['look-ahead'] })
    setDraft(null)
    setMessage(null)
  }
  const save = useMutation({ mutationFn: api.saveTalentPlan, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetTalentPlan, onSuccess: onSaved })

  const change = (next: PlanStep[], refused: string) => {
    const problem = firstProblem(next, index)
    if (problem) setMessage(`${refused}: ${problem}`)
    else {
      setDraft(next)
      setMessage(null)
    }
  }
  // The plan is "for" the tree with the most points in it.
  const mainSpec = [...perTree.entries()].sort((a, b) => b[1] - a[1])[0]
  const specName = tree.specs.find((s) => s.spec_id === mainSpec?.[0])?.name ?? view.plan.spec

  // Each planned step's levels: points come one a level from 10.
  const order = stepLevels(steps)

  return (
    <div className="talent-planner">
      <div className="talent-toolbar">
        <span className="muted">
          {total} point{total === 1 ? '' : 's'} planned · reaches level {total > 0 ? levelForPoint(total) : '—'}
        </span>
        {editing ? (
          <>
            <button
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate({ ...view.plan, spec: specName, steps })}
            >
              {save.isPending ? 'Saving…' : 'Save plan'}
            </button>
            <button type="button" className="secondary" onClick={() => (setDraft(null), setMessage(null))}>
              Discard
            </button>
            <button type="button" className="secondary" onClick={() => setDraft([])}>
              Clear
            </button>
          </>
        ) : (
          <>
            <button type="button" className="secondary" onClick={() => setDraft(view.plan.steps)}>
              Edit plan
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!view.customised || reset.isPending}
              onClick={() => reset.mutate()}
            >
              Reset to defaults
            </button>
          </>
        )}
      </div>
      {editing && (
        <p className="muted">
          Click a talent to add the next point; right-click or shift-click takes its last point off. Rows open
          after 5 points in a tree, and a talent with a prerequisite needs it maxed first.
        </p>
      )}
      {message && (
        <p className="warn" role="alert">
          {message}
        </p>
      )}
      {save.isError && <p className="error">{save.error.message}</p>}
      {reset.isError && <p className="error">{reset.error.message}</p>}

      <div className="talent-trees">
        {tree.specs.map((spec) => (
          <section key={spec.spec_id} className="talent-tree" aria-label={`${spec.name} tree`}>
            <h3>
              {spec.name} <span className="muted">{perTree.get(spec.spec_id) ?? 0}</span>
            </h3>
            <div className="talent-grid">
              {spec.nodes.map((node) => {
                const rank = planned.get(node.talent_id) ?? 0
                return (
                  <TalentButton
                    key={node.node_id}
                    node={node}
                    planned={rank}
                    spent={synced.get(node.talent_id) ?? 0}
                    locked={rank === 0 && firstProblem(addPoint(steps, node), index) !== null}
                    editing={editing}
                    onAdd={() => change(addPoint(steps, node), `Can't add ${node.name}`)}
                    onRemove={() => change(removePoint(steps, node.talent_id), `Can't take ${node.name} off`)}
                  />
                )
              })}
            </div>
          </section>
        ))}
      </div>

      {order.length > 0 && (
        <details className="talent-order" open={editing}>
          <summary>Order of points</summary>
          <ol>
            {order.map(({ step, from, to, points }, i) => (
              <li key={i}>
                {step.talent} → {step.rank}{' '}
                <span className="muted">
                  {points === 1 ? `level ${from}` : `levels ${from}–${to}`}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
