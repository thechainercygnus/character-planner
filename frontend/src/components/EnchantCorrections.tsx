import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type EnchantOption, type LevelSource, type Reagent } from '../api'
import { signed } from '../format'

const SOURCE_LABEL: Record<LevelSource, string> = {
  corrected: 'corrected',
  shipped: 'shipped band',
  item: 'item level',
}

/** Corrections change the enchant advice: refetch it and the corrections. */
function useCorrection<T>(mutationFn: (value: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['enchants'] }),
        queryClient.invalidateQueries({ queryKey: ['enchant-corrections'] }),
      ]),
  })
}

function MaterialRow({ reagent }: { reagent: Reagent }) {
  const [draft, setDraft] = useState<string | null>(null)
  const save = useCorrection(api.correctMaterial)
  const value = draft ?? (reagent.level !== null ? String(reagent.level) : '')
  const level = Number(value)
  const valid = Number.isInteger(level) && level >= 1 && level <= 60
  const corrected = reagent.level_source === 'corrected'

  return (
    <li className="material">
      <span>
        {reagent.quantity} × {reagent.name}
      </span>
      <input
        type="number"
        min={1}
        max={60}
        aria-label={`Level of ${reagent.name}`}
        value={value}
        placeholder="?"
        onChange={(event) => setDraft(event.target.value)}
      />
      {reagent.level_source && (
        <span className={corrected ? 'tag' : 'muted'}>{SOURCE_LABEL[reagent.level_source]}</span>
      )}
      {draft !== null && (
        <button
          type="button"
          className="link"
          disabled={!valid || save.isPending}
          onClick={() => save.mutate({ itemId: reagent.item_id, level }, { onSuccess: () => setDraft(null) })}
        >
          Save
        </button>
      )}
      {corrected && draft === null && (
        <button
          type="button"
          className="link"
          disabled={save.isPending}
          onClick={() => save.mutate({ itemId: reagent.item_id, level: null })}
        >
          Reset
        </button>
      )}
      {save.isError && <span className="error">{save.error.message}</span>}
    </li>
  )
}

type EffectRow = { name: string; value: string }

/** Add or fix the effect of a crafted enchant (a scope, an armor kit), keyed by its item. */
export function EffectEditor({
  itemId,
  effects,
  corrected,
  label,
}: {
  itemId: number
  effects: Record<string, number>
  corrected: boolean
  label: string
}) {
  const corrections = useQuery({ queryKey: ['enchant-corrections'], queryFn: api.enchantCorrections })
  const names = corrections.data?.effect_names ?? []
  const initial: EffectRow[] = Object.entries(effects).map(([name, value]) => ({ name, value: String(value) }))
  const [rows, setRows] = useState<EffectRow[] | null>(null)
  const current = rows ?? (initial.length > 0 ? initial : [{ name: names[0] ?? 'Stamina', value: '' }])
  const save = useCorrection(api.correctEffect)
  const parsed = Object.fromEntries(current.map((row) => [row.name, Number(row.value)]))
  const valid = current.length > 0 && current.every((row) => Number(row.value) > 0)

  const update = (index: number, change: Partial<EffectRow>) =>
    setRows(current.map((row, i) => (i === index ? { ...row, ...change } : row)))

  return (
    <div className="effect-editor" aria-label={`Effect of ${label}`}>
      {current.map((row, index) => (
        // Rows have no stable id, and two can name the same effect while editing; index
        // keys are fine because every input is controlled.
        // oxlint-disable-next-line react/no-array-index-key
        <div key={index} className="effect-row">
          <select
            aria-label="Effect"
            value={row.name}
            onChange={(event) => update(index, { name: event.target.value })}
          >
            {(names.includes(row.name) ? names : [row.name, ...names]).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            step="any"
            aria-label="Value"
            value={row.value}
            onChange={(event) => update(index, { value: event.target.value })}
          />
          {current.length > 1 && (
            <button type="button" className="link" onClick={() => setRows(current.filter((_, i) => i !== index))}>
              Remove
            </button>
          )}
        </div>
      ))}
      <div className="effect-actions">
        <button
          type="button"
          className="link"
          onClick={() => setRows([...current, { name: names.find((n) => !(n in parsed)) ?? 'Stamina', value: '' }])}
        >
          Add effect
        </button>
        <button
          type="button"
          className="link"
          disabled={!valid || save.isPending}
          onClick={() => save.mutate({ itemId, effects: parsed }, { onSuccess: () => setRows(null) })}
        >
          Save effect
        </button>
        {corrected && (
          <button
            type="button"
            className="link"
            disabled={save.isPending}
            onClick={() => save.mutate({ itemId, effects: null }, { onSuccess: () => setRows(null) })}
          >
            Reset effect
          </button>
        )}
        {corrected && <span className="tag">corrected</span>}
      </div>
      {save.isError && <p className="error">{save.error.message}</p>}
    </div>
  )
}

/** The materials behind an enchant's level estimate, and a crafted enchant's effect, to correct (#36). */
export function OptionCorrections({ option }: { option: EnchantOption }) {
  const corrected =
    option.reagents.some((r) => r.level_source === 'corrected') || option.effects_source === 'corrected'
  return (
    <details className="enchant-corrections">
      <summary>
        Materials{option.crafted_item_id !== null && ' and effect'}
        {corrected && <span className="tag">corrected</span>}
      </summary>
      {option.reagents.length > 0 ? (
        <ul className="materials">
          {option.reagents.map((reagent) => (
            <MaterialRow key={reagent.item_id} reagent={reagent} />
          ))}
        </ul>
      ) : (
        <p className="muted">No materials listed.</p>
      )}
      {option.crafted_item_id !== null && (
        <>
          <small className="muted">
            Effect{option.effects_source ? ` (${option.effects_source})` : ''}:{' '}
            {Object.entries(option.effects)
              .map(([stat, value]) => `${signed(value)} ${stat}`)
              .join(', ') || 'unknown'}
          </small>
          {option.effects_source !== 'equipped' ? (
            <EffectEditor
              itemId={option.crafted_item_id}
              effects={option.effects}
              corrected={option.effects_source === 'corrected'}
              label={option.name}
            />
          ) : (
            <small className="muted"> Read from your gear, so it isn't edited here.</small>
          )}
        </>
      )}
    </details>
  )
}

/** How many enchants to list per slot, with a reset to the shipped number. */
export function PerSlotControl({ perSlot, corrected }: { perSlot: number; corrected: boolean }) {
  const save = useCorrection(api.correctPerSlot)
  return (
    <label className="per-slot">
      Show{' '}
      <select value={perSlot} disabled={save.isPending} onChange={(event) => save.mutate(Number(event.target.value))}>
        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>{' '}
      per slot
      {corrected && (
        <button type="button" className="link" disabled={save.isPending} onClick={() => save.mutate(null)}>
          Reset
        </button>
      )}
    </label>
  )
}
