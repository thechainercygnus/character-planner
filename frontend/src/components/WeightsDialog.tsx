import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type WeightsView } from '../api'

type Draft = Record<string, string>

function toDraft(view: WeightsView): Draft {
  return Object.fromEntries(Object.entries(view.weights).map(([name, value]) => [name, String(value)]))
}

/** Parsed draft, or null when any field isn't a number in -10..10. */
function parseDraft(draft: Draft): Record<string, number> | null {
  const parsed: Record<string, number> = {}
  for (const [name, text] of Object.entries(draft)) {
    const value = Number(text)
    if (text.trim() === '' || !Number.isFinite(value) || value < -10 || value > 10) return null
    parsed[name] = value
  }
  return parsed
}

/**
 * "Stat weights" button that opens a modal editor.
 *
 * Uses the native <dialog> element: showModal() gives us focus trapping, Esc to close
 * and an inert page behind it for free. Closing discards unapplied edits.
 */
export function WeightsDialog() {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const weights = useQuery({ queryKey: ['weights'], queryFn: api.weights })
  // Draft edits; null means "show what the server has".
  const [draft, setDraft] = useState<Draft | null>(null)

  const onSaved = (view: WeightsView) => {
    queryClient.setQueryData(['weights'], view)
    setDraft(null)
    return queryClient.invalidateQueries({ queryKey: ['gear'] })
  }
  const save = useMutation({ mutationFn: api.saveWeights, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetWeights, onSuccess: onSaved })

  const close = () => dialogRef.current?.close()

  if (weights.isError) return <span className="error">Couldn't load stat weights: {weights.error.message}</span>

  const view = weights.data
  const shown = draft ?? (view ? toDraft(view) : {})
  const parsed = parseDraft(shown)
  const dirty = draft !== null

  return (
    <>
      <button
        type="button"
        className="secondary"
        disabled={!view}
        onClick={() => dialogRef.current?.showModal()}
      >
        Stat weights{view?.customised && <span className="customised-dot"> • customised</span>}
      </button>

      <dialog
        ref={dialogRef}
        className="weights-dialog"
        aria-labelledby="weights-title"
        onClose={() => setDraft(null)}
        // A click on the backdrop lands on the <dialog> itself, not its content.
        onClick={(event) => {
          if (event.target === event.currentTarget) close()
        }}
      >
        {view && (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (parsed) save.mutate(parsed)
            }}
          >
            <header className="weights-dialog-header">
              <h2 id="weights-title">
                Stat weights <span className="muted">{view.customised ? 'customised' : 'defaults'}</span>
              </h2>
              <button type="button" className="secondary" aria-label="Close" onClick={close}>
                ✕
              </button>
            </header>
            <p className="muted">
              Score = sum of stat × weight, plus armor and weapon DPS. Gear targets are ranked by score gain over what
              you wear.
            </p>

            <div className="weights">
              {Object.keys(shown).map((name) => {
                const changed = Number(shown[name]) !== view.defaults[name]
                return (
                  <label key={name} className={changed ? 'changed' : undefined}>
                    <span>{name}</span>
                    <input
                      type="number"
                      step="0.05"
                      min={-10}
                      max={10}
                      value={shown[name]}
                      onChange={(event) => setDraft({ ...shown, [name]: event.target.value })}
                    />
                    {changed && <small className="muted">default {view.defaults[name]}</small>}
                  </label>
                )
              })}
            </div>

            <footer className="weights-actions">
              <button type="submit" disabled={!dirty || parsed === null || save.isPending}>
                {save.isPending ? 'Applying…' : 'Apply'}
              </button>
              <button type="button" className="secondary" disabled={!dirty} onClick={() => setDraft(null)}>
                Discard
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!view.customised || reset.isPending}
                onClick={() => reset.mutate()}
              >
                Reset to defaults
              </button>
              {parsed === null && <span className="error">Weights must be numbers from -10 to 10.</span>}
              {save.isError && <span className="error">{save.error.message}</span>}
            </footer>
          </form>
        )}
      </dialog>
    </>
  )
}
