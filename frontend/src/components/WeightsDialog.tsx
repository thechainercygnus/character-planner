import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type WeightsView } from '../api'

type Draft = Record<string, string>
/** Which name the inline name field is for, if it's open. */
type Naming = 'save-as' | 'rename' | null

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
 * "Stat weights" button that opens a modal editor with a preset picker (ADR 0013).
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
  const [naming, setNaming] = useState<Naming>(null)
  const [nameText, setNameText] = useState('')

  const onSaved = (view: WeightsView) => {
    queryClient.setQueryData(['weights'], view)
    setDraft(null)
    setNaming(null)
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: ['gear'] }),
      queryClient.invalidateQueries({ queryKey: ['look-ahead'] }),
      queryClient.invalidateQueries({ queryKey: ['recommendations'] }),
      queryClient.invalidateQueries({ queryKey: ['progress'] }), // gear score uses the weights
      queryClient.invalidateQueries({ queryKey: ['enchants'] }),
    ])
  }
  const save = useMutation({ mutationFn: api.saveWeights, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetWeights, onSuccess: onSaved })
  const activate = useMutation({ mutationFn: api.activatePreset, onSuccess: onSaved })
  const create = useMutation({ mutationFn: api.createPreset, onSuccess: onSaved })
  const rename = useMutation({ mutationFn: api.renamePreset, onSuccess: onSaved })
  const remove = useMutation({ mutationFn: api.deletePreset, onSuccess: onSaved })
  const mutations = [save, reset, activate, create, rename, remove]
  const busy = mutations.some((m) => m.isPending)
  const error = mutations.find((m) => m.isError)?.error

  const close = () => dialogRef.current?.close()

  if (weights.isError) return <span className="error">Couldn't load stat weights: {weights.error.message}</span>

  const view = weights.data
  const shown = draft ?? (view ? toDraft(view) : {})
  const parsed = parseDraft(shown)
  const dirty = draft !== null
  const active = view?.presets.find((preset) => preset.key === view.preset)

  const startNaming = (mode: Naming) => {
    setNaming(mode)
    setNameText(mode === 'rename' ? (active?.name ?? '') : '')
  }
  const submitName = () => {
    const name = nameText.trim()
    if (!name || !view) return
    if (naming === 'rename') rename.mutate({ key: view.preset, name })
    else if (parsed) create.mutate({ name, weights: parsed })
  }

  return (
    <>
      <button
        type="button"
        className="secondary"
        disabled={!view}
        onClick={() => dialogRef.current?.showModal()}
      >
        Stat weights{active && `: ${active.name}`}
        {view?.customised && <span className="customised-dot"> • customised</span>}
      </button>

      <dialog
        ref={dialogRef}
        className="weights-dialog"
        aria-labelledby="weights-title"
        onClose={() => {
          setDraft(null)
          setNaming(null)
        }}
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
                Stat weights <span className="muted">{view.customised ? 'customised' : active?.name}</span>
              </h2>
              <button type="button" className="secondary" aria-label="Close" onClick={close}>
                ✕
              </button>
            </header>

            <div className="preset-bar">
              <label>
                Preset{' '}
                <select
                  value={view.preset}
                  disabled={busy}
                  onChange={(event) => activate.mutate(event.target.value)}
                >
                  {view.presets.map((preset) => (
                    <option key={preset.key} value={preset.key}>
                      {preset.name}
                      {preset.customised ? ' (customised)' : ''}
                      {preset.shipped ? '' : ' (yours)'}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="secondary" disabled={busy || parsed === null} onClick={() => startNaming('save-as')}>
                Save as…
              </button>
              {active && !active.shipped && (
                <>
                  <button type="button" className="secondary" disabled={busy} onClick={() => startNaming('rename')}>
                    Rename…
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Delete the preset ${active.name}?`)) remove.mutate(view.preset)
                    }}
                  >
                    Delete
                  </button>
                </>
              )}
            </div>

            {naming && (
              <div className="preset-name">
                <label>
                  {naming === 'rename' ? 'New name' : 'Name for the new preset'}{' '}
                  <input
                    autoFocus
                    maxLength={40}
                    value={nameText}
                    onChange={(event) => setNameText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        submitName()
                      }
                    }}
                  />
                </label>
                <button type="button" disabled={busy || !nameText.trim()} onClick={submitName}>
                  {naming === 'rename' ? 'Rename' : 'Save preset'}
                </button>
                <button type="button" className="secondary" onClick={() => setNaming(null)}>
                  Cancel
                </button>
              </div>
            )}

            <p className="muted">
              Score = sum of stat × weight, plus armor and weapon DPS. Gear targets are ranked by score gain over what
              you wear. The active preset scores every tab.
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
              <button type="submit" disabled={!dirty || parsed === null || busy}>
                {save.isPending ? 'Applying…' : 'Apply'}
              </button>
              <button type="button" className="secondary" disabled={!dirty} onClick={() => setDraft(null)}>
                Discard
              </button>
              {active?.shipped && (
                <button
                  type="button"
                  className="secondary"
                  disabled={!view.customised || busy}
                  onClick={() => reset.mutate()}
                >
                  Reset to defaults
                </button>
              )}
              {parsed === null && <span className="error">Weights must be numbers from -10 to 10.</span>}
              {error && <span className="error">{error.message}</span>}
            </footer>
          </form>
        )}
      </dialog>
    </>
  )
}
