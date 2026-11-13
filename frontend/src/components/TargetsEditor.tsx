import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, EQUIPMENT_SLOTS, slotLabel, type GearTarget, type GearTargets, type PoolItem } from '../api'
import { sourceText } from '../format'

/** An error message for the first problem, or null when the targets can be saved. */
function problem(targets: GearTarget[]): string | null {
  if (targets.some((t) => t.item.trim() === '')) return 'Every target needs an item name.'
  if (targets.some((t) => t.level !== null && (!Number.isInteger(t.level) || t.level < 1 || t.level > 80)))
    return 'Levels must be whole numbers from 1 to 80, or blank.'
  return null
}

function blankTarget(slot: string): GearTarget {
  return {
    slot,
    item: '',
    source: '',
    priority: null,
    level: null,
    pinned: false,
    item_id: null,
    item_level: null,
    armor_type: null,
    armor: null,
    stats: {},
  }
}

/**
 * Plan tab: edit the gear targets in a modal (ADR 0014, 0015). One list, shown by slot; a
 * slot's order breaks ties between targets at the same level. The YAML stays the default.
 */
export function TargetsEditor({ customised }: { customised: boolean }) {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const targets = useQuery({ queryKey: ['targets'], queryFn: api.targets, enabled: open })
  const pool = useQuery({ queryKey: ['pool'], queryFn: api.pool, enabled: open })
  const [draft, setDraft] = useState<GearTarget[] | null>(null)
  const [newSlot, setNewSlot] = useState<string>(EQUIPMENT_SLOTS[0])

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

  const list = draft ?? targets.data?.targets ?? []
  const error = problem(list)
  const poolItems = pool.data?.items ?? []
  const byName = new Map<string, PoolItem>(poolItems.map((item) => [item.name.toLowerCase(), item]))
  const byId = new Map<number, PoolItem>(poolItems.map((item) => [item.item_id, item]))
  // Slots with targets, in equipment order.
  const slots = EQUIPMENT_SLOTS.filter((slot) => list.some((t) => t.slot === slot))

  const setTarget = (index: number, change: Partial<GearTarget>) =>
    setDraft(list.map((target, i) => (i === index ? { ...target, ...change } : target)))
  const rename = (index: number, item: string) => {
    // A pool item's name fills in its id, and its source when there's none yet.
    const match = byName.get(item.trim().toLowerCase())
    const current = list[index]
    setTarget(index, {
      item,
      item_id: match?.item_id ?? null,
      source: match && !current.source ? match.sources.map(sourceText).join('; ') : current.source,
    })
  }
  /** Swap a target with another in the same slot. */
  const swap = (index: number, other: number) => {
    const next = [...list]
    ;[next[index], next[other]] = [next[other], next[index]]
    setDraft(next)
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
            if (error === null) save.mutate({ targets: list })
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
            The Plan tab shows each slot's target for your level and the ones coming up. <strong>Level</strong> is when
            you plan to go for an item: leave it blank to use the item's own level, which also wins when it's higher.
            Within a slot, order breaks ties. Names from the item pool fill in the item id and source. Pinned targets are
            always listed on the Upgrades tab until worn.
          </p>
          {targets.isPending && <p className="muted">Loading targets…</p>}
          {targets.isError && <p className="error">Couldn't load targets: {targets.error.message}</p>}

          <datalist id="pool-items">
            {poolItems.map((item) => (
              <option key={item.item_id} value={item.name} />
            ))}
          </datalist>

          {slots.map((slot) => {
            const label = slotLabel(slot)
            const indices = list.flatMap((target, i) => (target.slot === slot ? [i] : []))
            return (
              <fieldset key={slot} className="target-slot">
                <legend>{label}</legend>
                <ol className="target-rows">
                  {indices.map((index, n) => {
                    const target = list[index]
                    const name = `${label} target ${n + 1}`
                    const ownLevel = target.item_id !== null ? byId.get(target.item_id)?.effective_level : null
                    return (
                      // Rows have no stable id; index keys are fine because the inputs are controlled.
                      <li key={index}>
                        <input
                          aria-label={`${name} item`}
                          list="pool-items"
                          placeholder="Item name"
                          value={target.item}
                          onChange={(event) => rename(index, event.target.value)}
                        />
                        <input
                          aria-label={`${name} source`}
                          placeholder="Where it comes from"
                          value={target.source}
                          onChange={(event) => setTarget(index, { source: event.target.value })}
                        />
                        <input
                          aria-label={`${name} level`}
                          className="level-input"
                          type="number"
                          min={1}
                          max={80}
                          placeholder={ownLevel ? String(ownLevel) : 'auto'}
                          title="Not before this level. Blank: the item's own level."
                          value={target.level ?? ''}
                          onChange={(event) =>
                            setTarget(index, { level: event.target.value === '' ? null : Number(event.target.value) })
                          }
                        />
                        <label className="pin-toggle" title="Always list it on the Upgrades tab until worn">
                          <input
                            type="checkbox"
                            aria-label={`${name} pinned`}
                            checked={target.pinned}
                            onChange={(event) => setTarget(index, { pinned: event.target.checked })}
                          />{' '}
                          Pinned
                        </label>
                        <button
                          type="button"
                          className="secondary"
                          aria-label={`Move ${name} up`}
                          disabled={n === 0}
                          onClick={() => swap(index, indices[n - 1])}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          aria-label={`Move ${name} down`}
                          disabled={n === indices.length - 1}
                          onClick={() => swap(index, indices[n + 1])}
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          aria-label={`Remove ${name}`}
                          onClick={() => setDraft(list.filter((_, i) => i !== index))}
                        >
                          ✕
                        </button>
                      </li>
                    )
                  })}
                </ol>
                <button type="button" className="link" onClick={() => setDraft([...list, blankTarget(slot)])}>
                  Add {label.toLowerCase()} target
                </button>
              </fieldset>
            )
          })}
          {targets.data && (
            <div className="add-slot">
              <select
                aria-label="Slot for a new target"
                value={newSlot}
                onChange={(event) => setNewSlot(event.target.value)}
              >
                {EQUIPMENT_SLOTS.map((slot) => (
                  <option key={slot} value={slot}>
                    {slotLabel(slot)}
                  </option>
                ))}
              </select>{' '}
              <button type="button" className="secondary" onClick={() => setDraft([...list, blankTarget(newSlot)])}>
                Add target
              </button>
            </div>
          )}

          <footer className="weights-actions">
            <button type="submit" disabled={draft === null || error !== null || save.isPending}>
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
            {draft !== null && error !== null && <span className="error">{error}</span>}
            {save.isError && <span className="error">{save.error.message}</span>}
            {reset.isError && <span className="error">{reset.error.message}</span>}
          </footer>
        </form>
      </dialog>
    </>
  )
}
