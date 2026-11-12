import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, EQUIPMENT_SLOTS, slotLabel, type GearTarget, type GearTargets, type PoolItem } from '../api'
import { sourceText } from '../format'

/** A target as edited: the level is text until saved; everything else rides along. */
type DraftBracket = { minLevel: string; targets: GearTarget[] }

function toDraft(targets: GearTargets): DraftBracket[] {
  return targets.brackets.map((b) => ({ minLevel: String(b.min_level), targets: b.targets }))
}

/** Saveable targets, or an error message for the first problem. */
function parseDraft(draft: DraftBracket[]): GearTargets | string {
  const levels = new Set<number>()
  const brackets = []
  for (const bracket of draft) {
    const level = Number(bracket.minLevel)
    if (!Number.isInteger(level) || level < 1 || level > 80) return 'Bracket levels must be whole numbers from 1 to 80.'
    if (levels.has(level)) return `There are two brackets for level ${level}.`
    levels.add(level)
    if (bracket.targets.some((t) => t.item.trim() === '')) return 'Every target needs an item name.'
    brackets.push({ min_level: level, targets: bracket.targets })
  }
  return { brackets }
}

function blankTarget(): GearTarget {
  return {
    slot: 'HEAD',
    item: '',
    source: '',
    priority: null,
    item_id: null,
    item_level: null,
    armor_type: null,
    armor: null,
    stats: {},
  }
}

/** Plan tab: edit the gear targets in a modal (ADR 0014). The YAML stays the default. */
export function TargetsEditor({ customised }: { customised: boolean }) {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const targets = useQuery({ queryKey: ['targets'], queryFn: api.targets, enabled: open })
  const pool = useQuery({ queryKey: ['pool'], queryFn: api.pool, enabled: open })
  const [draft, setDraft] = useState<DraftBracket[] | null>(null)

  const onSaved = (saved: GearTargets) => {
    queryClient.setQueryData(['targets'], saved)
    setDraft(null)
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: ['gear'] }),
      queryClient.invalidateQueries({ queryKey: ['recommendations'] }),
    ])
  }
  const save = useMutation({ mutationFn: api.saveTargets, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetTargets, onSuccess: onSaved })

  const brackets = draft ?? (targets.data ? toDraft(targets.data) : [])
  const parsed = parseDraft(brackets)
  const byName = new Map<string, PoolItem>((pool.data?.items ?? []).map((item) => [item.name.toLowerCase(), item]))

  const setBracket = (index: number, bracket: DraftBracket) =>
    setDraft(brackets.map((b, i) => (i === index ? bracket : b)))
  const setTarget = (b: number, t: number, change: Partial<GearTarget>) =>
    setBracket(b, {
      ...brackets[b],
      targets: brackets[b].targets.map((target, i) => (i === t ? { ...target, ...change } : target)),
    })
  const rename = (b: number, t: number, item: string) => {
    // A pool item's name fills in its id, and its source when there's none yet.
    const match = byName.get(item.trim().toLowerCase())
    const current = brackets[b].targets[t]
    setTarget(b, t, {
      item,
      item_id: match?.item_id ?? null,
      source: match && !current.source ? match.sources.map(sourceText).join('; ') : current.source,
    })
  }
  const move = (b: number, t: number, by: number) => {
    const next = [...brackets[b].targets]
    const [row] = next.splice(t, 1)
    next.splice(t + by, 0, row)
    setBracket(b, { ...brackets[b], targets: next })
  }
  const addBracket = () => {
    const highest = Math.max(0, ...brackets.map((b) => Number(b.minLevel) || 0))
    setDraft([...brackets, { minLevel: String(highest + 5), targets: [] }])
  }

  return (
    <>
      <button
        type="button"
        className="secondary"
        onClick={() => {
          setOpen(true)
          dialogRef.current?.showModal()
        }}
      >
        Edit targets{customised && <span className="customised-dot"> • customised</span>}
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog targets-dialog"
        aria-labelledby="targets-title"
        onClose={() => setDraft(null)}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close()
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (typeof parsed !== 'string') save.mutate(parsed)
          }}
        >
          <header className="weights-dialog-header">
            <h2 id="targets-title">
              Gear targets <span className="muted">{customised ? 'customised' : 'default'}</span>
            </h2>
            <button type="button" className="secondary" aria-label="Close" onClick={() => dialogRef.current?.close()}>
              ✕
            </button>
          </header>
          <p className="muted">
            Each bracket applies from its level until the next one. Order sets priority. Names from the item pool fill
            in the item id and source; <strong>Make target</strong> on the Upgrades tab adds to your current bracket.
          </p>
          {targets.isPending && <p className="muted">Loading targets…</p>}
          {targets.isError && <p className="error">Couldn't load targets: {targets.error.message}</p>}

          <datalist id="pool-items">
            {(pool.data?.items ?? []).map((item) => (
              <option key={item.item_id} value={item.name} />
            ))}
          </datalist>

          {brackets.map((bracket, b) => (
            // Brackets and rows have no stable id; index keys are fine because the inputs are controlled.
            <fieldset key={b} className="target-bracket">
              <legend>
                <label>
                  From level{' '}
                  <input
                    aria-label={`Bracket ${b + 1} level`}
                    type="number"
                    min={1}
                    max={80}
                    value={bracket.minLevel}
                    onChange={(event) => setBracket(b, { ...bracket, minLevel: event.target.value })}
                  />
                </label>
                <button
                  type="button"
                  className="link"
                  onClick={() => setDraft(brackets.filter((_, i) => i !== b))}
                >
                  Remove bracket
                </button>
              </legend>
              <ol className="target-rows">
                {bracket.targets.map((target, t) => (
                  <li key={t}>
                    <select
                      aria-label={`Bracket ${b + 1} target ${t + 1} slot`}
                      value={target.slot}
                      onChange={(event) => setTarget(b, t, { slot: event.target.value })}
                    >
                      {EQUIPMENT_SLOTS.map((slot) => (
                        <option key={slot} value={slot}>
                          {slotLabel(slot)}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label={`Bracket ${b + 1} target ${t + 1} item`}
                      list="pool-items"
                      placeholder="Item name"
                      value={target.item}
                      onChange={(event) => rename(b, t, event.target.value)}
                    />
                    <input
                      aria-label={`Bracket ${b + 1} target ${t + 1} source`}
                      placeholder="Where it comes from"
                      value={target.source}
                      onChange={(event) => setTarget(b, t, { source: event.target.value })}
                    />
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Move bracket ${b + 1} target ${t + 1} up`}
                      disabled={t === 0}
                      onClick={() => move(b, t, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Move bracket ${b + 1} target ${t + 1} down`}
                      disabled={t === bracket.targets.length - 1}
                      onClick={() => move(b, t, 1)}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Remove bracket ${b + 1} target ${t + 1}`}
                      onClick={() =>
                        setBracket(b, { ...bracket, targets: bracket.targets.filter((_, i) => i !== t) })
                      }
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ol>
              <button
                type="button"
                className="link"
                onClick={() => setBracket(b, { ...bracket, targets: [...bracket.targets, blankTarget()] })}
              >
                Add target
              </button>
            </fieldset>
          ))}
          {targets.data && (
            <button type="button" className="secondary" onClick={addBracket}>
              Add bracket
            </button>
          )}

          <footer className="weights-actions">
            <button type="submit" disabled={draft === null || typeof parsed === 'string' || save.isPending}>
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="secondary" disabled={draft === null} onClick={() => setDraft(null)}>
              Discard
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!customised || reset.isPending}
              onClick={() => reset.mutate()}
            >
              Reset to defaults
            </button>
            {draft !== null && typeof parsed === 'string' && <span className="error">{parsed}</span>}
            {save.isError && <span className="error">{save.error.message}</span>}
            {reset.isError && <span className="error">{reset.error.message}</span>}
          </footer>
        </form>
      </dialog>
    </>
  )
}
