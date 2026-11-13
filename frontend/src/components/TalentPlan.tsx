import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type PlanStep, type StepStatus, type TalentPlanView } from '../api'
import { TalentTrees } from './TalentTrees'

const STATE_MARK: Record<StepStatus['state'], string> = { done: '✓', partial: '◐', pending: '○' }

function StepRow({ step }: { step: StepStatus }) {
  return (
    <li className={`talent-step ${step.state}`}>
      <span className="step-mark" aria-label={step.state}>
        {STATE_MARK[step.state]}
      </span>
      <span>
        {step.talent} <span className="muted">→ {step.rank}</span>
      </span>
      <span className="muted">
        {step.state === 'done'
          ? `${step.current}/${step.rank}`
          : `${step.current}/${step.rank} · by level ${step.level}`}
      </span>
    </li>
  )
}

type Draft = { talent: string; rank: string }[]

function toDraft(steps: PlanStep[]): Draft {
  return steps.map((step) => ({ talent: step.talent, rank: String(step.rank) }))
}

function parseDraft(draft: Draft): PlanStep[] | null {
  const steps: PlanStep[] = []
  for (const row of draft) {
    const rank = Number(row.rank)
    if (row.talent.trim() === '' || !Number.isInteger(rank) || rank < 1 || rank > 10) return null
    steps.push({ talent: row.talent.trim(), rank })
  }
  return steps
}

/** Edit the plan in a modal: ordered rows of talent + target rank. */
function PlanEditor({ view }: { view: TalentPlanView }) {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const rows = draft ?? toDraft(view.plan.steps)
  const parsed = parseDraft(rows)

  const onSaved = (saved: TalentPlanView) => {
    queryClient.setQueryData(['talents'], saved)
    setDraft(null)
  }
  const save = useMutation({ mutationFn: api.saveTalentPlan, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetTalentPlan, onSuccess: onSaved })

  // Names to suggest: what's in the plan and what's been spent in game.
  const known = [...new Set([...view.plan.steps.map((s) => s.talent), ...view.off_plan.map((o) => o.talent)])]

  const update = (index: number, field: 'talent' | 'rank', value: string) =>
    setDraft(rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)))
  const move = (index: number, by: number) => {
    const next = [...rows]
    const [row] = next.splice(index, 1)
    next.splice(index + by, 0, row)
    setDraft(next)
  }

  return (
    <>
      <button type="button" className="secondary" onClick={() => dialogRef.current?.showModal()}>
        Edit plan
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog"
        aria-labelledby="talent-plan-title"
        onClose={() => setDraft(null)}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close()
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (parsed) save.mutate({ spec: view.plan.spec, steps: parsed })
          }}
        >
          <header className="weights-dialog-header">
            <h2 id="talent-plan-title">
              Talent plan <span className="muted">{view.customised ? 'customised' : 'default'}</span>
            </h2>
            <button type="button" className="secondary" aria-label="Close" onClick={() => dialogRef.current?.close()}>
              ✕
            </button>
          </header>
          <p className="muted">
            Steps in spending order. Each raises a talent to a rank; a talent can appear again later with a higher
            rank.
          </p>

          <datalist id="known-talents">
            {known.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <ol className="plan-rows">
            {rows.map((row, index) => (
              // Rows have no stable id; index keys are fine because the inputs are controlled.
              <li key={index}>
                <input
                  aria-label={`Step ${index + 1} talent`}
                  list="known-talents"
                  value={row.talent}
                  onChange={(event) => update(index, 'talent', event.target.value)}
                />
                <input
                  aria-label={`Step ${index + 1} rank`}
                  type="number"
                  min={1}
                  max={10}
                  value={row.rank}
                  onChange={(event) => update(index, 'rank', event.target.value)}
                />
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Move step ${index + 1} up`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Move step ${index + 1} down`}
                  disabled={index === rows.length - 1}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Remove step ${index + 1}`}
                  onClick={() => setDraft(rows.filter((_, i) => i !== index))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ol>
          <button type="button" className="secondary" onClick={() => setDraft([...rows, { talent: '', rank: '1' }])}>
            Add step
          </button>

          <footer className="weights-actions">
            <button type="submit" disabled={draft === null || parsed === null || save.isPending}>
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="secondary" disabled={draft === null} onClick={() => setDraft(null)}>
              Discard
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!view.customised || reset.isPending}
              onClick={() => reset.mutate()}
            >
              Reset to default
            </button>
            {parsed === null && <span className="error">Every step needs a talent and a rank from 1 to 10.</span>}
            {save.isError && <span className="error">{save.error.message}</span>}
          </footer>
        </form>
      </dialog>
    </>
  )
}

/**
 * The talent plan against the synced talents: next point, progress, points off plan
 * (ADR 0009), on the class's talent trees once they're loaded (#88).
 */
export function TalentPlanPanel({ view }: { view: TalentPlanView }) {
  const trees = useQuery({
    queryKey: ['talent-tree'],
    queryFn: api.talentTree,
    // The trees load in the background after the first sync, and their icons after them:
    // check again until the trees are in and the refresh has finished.
    refetchInterval: (query) => {
      const data = query.state.data
      return data && (!data.tree || data.loading) ? 5_000 : false
    },
  })
  const tree = trees.data?.tree ?? null
  const specMismatch = view.current_spec !== null && view.current_spec !== view.spec
  const unspent =
    view.available !== null && view.spent !== null && view.available > view.spent
      ? view.available - view.spent
      : 0

  return (
    <section>
      <div className="section-heading">
        <h2>
          Talents{' '}
          <span className="muted">
            {view.spent ?? '?'}/{view.available ?? '?'} points · plan {view.planned_points} points in {view.spec}
          </span>
        </h2>
        {!tree && <PlanEditor view={view} />}
      </div>
      {!tree && trees.data?.class_name && (
        <p className="muted">
          {trees.data.loading
            ? `Loading the ${trees.data.class_name} talent trees…`
            : `The ${trees.data.class_name} talent trees aren't loaded yet: they load after a sync.`}
        </p>
      )}
      {tree && <TalentTrees tree={tree} view={view} />}

      {specMismatch && (
        <p className="warn">
          Your points are mostly in {view.current_spec}, but the plan is for {view.spec}.
        </p>
      )}
      {unspent > 0 && (
        <p className="warn">
          {unspent} unspent point{unspent === 1 ? '' : 's'}.
        </p>
      )}

      {view.next ? (
        <p className="next-talent">
          Next: <strong>{view.next.talent}</strong> {view.next.rank}{' '}
          <span className="muted">
            {view.level !== null && view.next.level <= view.level ? 'available now' : `at level ${view.next.level}`}
          </span>
        </p>
      ) : (
        <p className="muted">Every planned point is spent. Extend the plan to see what's next.</p>
      )}

      {view.off_plan.length > 0 && (
        <div className="off-plan">
          <p className="warn">Off plan:</p>
          <ul>
            {view.off_plan.map((entry) => (
              <li key={entry.talent}>
                {entry.talent} {entry.current}{' '}
                <span className="muted">
                  {entry.planned === 0 ? '(not in the plan)' : `(plan has ${entry.planned})`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ol className="talent-steps">
        {view.steps.map((step) => (
          <StepRow key={`${step.talent}-${step.first_point}`} step={step} />
        ))}
      </ol>
    </section>
  )
}
