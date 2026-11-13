import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type RulesView, type UsageRules } from '../api'

/** Numbers are text while edited; the lists and toggle ride along. */
type Draft = Pick<
  UsageRules,
  'weapon_types' | 'armor_types' | 'two_handers' | 'two_hand_types' | 'off_hand_types'
> & {
  plate_from_level: string
  mail_from_level: string
  dual_wield_from_level: string
  levels_ahead: string
  per_slot: string
  min_gain: string
}

function toDraft(rules: UsageRules): Draft {
  return {
    ...rules,
    plate_from_level: rules.plate_from_level === null ? '' : String(rules.plate_from_level),
    mail_from_level: rules.mail_from_level === null ? '' : String(rules.mail_from_level),
    dual_wield_from_level: rules.dual_wield_from_level === null ? '' : String(rules.dual_wield_from_level),
    levels_ahead: String(rules.levels_ahead),
    per_slot: String(rules.per_slot),
    min_gain: String(rules.min_gain),
  }
}

function wholeNumber(text: string, low: number, high: number): number | null {
  const value = Number(text)
  return text.trim() !== '' && Number.isInteger(value) && value >= low && value <= high ? value : null
}

/** Saveable rules, or an error message for the first problem. */
function parseDraft(draft: Draft): UsageRules | string {
  const plate = draft.plate_from_level.trim() === '' ? null : wholeNumber(draft.plate_from_level, 1, 80)
  if (draft.plate_from_level.trim() !== '' && plate === null) return 'Plate level must be 1 to 80, or blank for never.'
  const mail = draft.mail_from_level.trim() === '' ? null : wholeNumber(draft.mail_from_level, 1, 80)
  if (draft.mail_from_level.trim() !== '' && mail === null) return 'Mail level must be 1 to 80, or blank for never.'
  const dualWield =
    draft.dual_wield_from_level.trim() === '' ? null : wholeNumber(draft.dual_wield_from_level, 1, 80)
  if (draft.dual_wield_from_level.trim() !== '' && dualWield === null)
    return 'Dual wield level must be 1 to 80, or blank for from the start.'
  const levelsAhead = wholeNumber(draft.levels_ahead, 0, 20)
  if (levelsAhead === null) return 'Levels ahead must be a whole number from 0 to 20.'
  const perSlot = wholeNumber(draft.per_slot, 1, 10)
  if (perSlot === null) return 'Upgrades per slot must be a whole number from 1 to 10.'
  const minGain = Number(draft.min_gain)
  if (draft.min_gain.trim() === '' || !Number.isFinite(minGain) || minGain < 0 || minGain > 100)
    return 'Minimum gain must be a number from 0 to 100.'
  return {
    weapon_types: draft.weapon_types,
    armor_types: draft.armor_types,
    plate_from_level: plate,
    mail_from_level: mail,
    two_handers: draft.two_handers,
    two_hand_types: draft.two_hand_types,
    off_hand_types: draft.off_hand_types,
    dual_wield_from_level: dualWield,
    levels_ahead: levelsAhead,
    per_slot: perSlot,
    min_gain: minGain,
  }
}

const LABELS: Record<string, string> = { Miscellaneous: 'Held in off-hand', cloth: 'Cloth', leather: 'Leather', mail: 'Mail' }

/** Checkboxes for one list of types. */
function TypeChoices({
  legend,
  options,
  chosen,
  onChange,
}: {
  legend: string
  options: string[]
  chosen: string[]
  onChange: (chosen: string[]) => void
}) {
  return (
    <fieldset className="rule-types">
      <legend>{legend}</legend>
      {options.map((option) => (
        <label key={option}>
          <input
            type="checkbox"
            checked={chosen.includes(option)}
            onChange={(event) =>
              onChange(event.target.checked ? [...chosen, option] : chosen.filter((value) => value !== option))
            }
          />{' '}
          {LABELS[option] ?? option}
        </label>
      ))}
    </fieldset>
  )
}

/**
 * Upgrades tab: "Upgrades settings" opens a modal editor for the rules (ADR 0016): what the
 * character can wear and how many upgrades to list. recommend.yaml stays the default.
 */
export function RulesDialog() {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const rules = useQuery({ queryKey: ['rules'], queryFn: api.rules })
  const [draft, setDraft] = useState<Draft | null>(null)

  const onSaved = (view: RulesView) => {
    queryClient.setQueryData(['rules'], view)
    setDraft(null)
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: ['recommendations'] }),
      queryClient.invalidateQueries({ queryKey: ['enchants'] }), // enchant fit uses two_handers and levels ahead
    ])
  }
  const save = useMutation({ mutationFn: api.saveRules, onSuccess: onSaved })
  const reset = useMutation({ mutationFn: api.resetRules, onSuccess: onSaved })
  const busy = save.isPending || reset.isPending
  const close = () => dialogRef.current?.close()

  if (rules.isError) return <span className="error">Couldn't load the Upgrades settings: {rules.error.message}</span>

  const view = rules.data
  const shown = draft ?? (view ? toDraft(view.rules) : null)
  const parsed = shown ? parseDraft(shown) : null
  const change = (update: Partial<Draft>) => shown && setDraft({ ...shown, ...update })

  return (
    <>
      <button type="button" className="secondary" disabled={!view} onClick={() => dialogRef.current?.showModal()}>
        Upgrades settings{view?.customised && <span className="customised-dot"> • customised</span>}
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog rules-dialog"
        aria-labelledby="rules-title"
        onClose={() => setDraft(null)}
        onClick={(event) => {
          if (event.target === event.currentTarget) close()
        }}
      >
        {view && shown && (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (parsed && typeof parsed !== 'string') save.mutate(parsed)
            }}
          >
            <header className="weights-dialog-header">
              <h2 id="rules-title">
                Upgrades settings <span className="muted">{view.customised ? 'customised' : 'default'}</span>
              </h2>
              <button type="button" className="secondary" aria-label="Close" onClick={close}>
                ✕
              </button>
            </header>
            <p className="muted">
              What your character can and wants to wear, and how the Upgrades tab lists items. To hide one item, use{' '}
              <strong>Never suggest</strong> on it instead.
            </p>

            <TypeChoices
              legend="Weapon types"
              options={view.weapon_type_options}
              chosen={shown.weapon_types}
              onChange={(weapon_types) => change({ weapon_types })}
            />
            <TypeChoices
              legend="Armor"
              options={view.armor_type_options}
              chosen={shown.armor_types}
              onChange={(armor_types) => change({ armor_types })}
            />
            {shown.two_handers && (
              <TypeChoices
                legend="Two-handed weapon types"
                options={view.two_hand_type_options}
                // null means any: show every type as chosen.
                chosen={shown.two_hand_types ?? view.two_hand_type_options}
                onChange={(chosen) =>
                  change({
                    two_hand_types: chosen.length === view.two_hand_type_options.length ? null : chosen,
                  })
                }
              />
            )}
            <TypeChoices
              legend="Off hand"
              options={view.off_hand_type_options}
              chosen={shown.off_hand_types}
              onChange={(off_hand_types) => change({ off_hand_types })}
            />

            <div className="rule-numbers">
              <label>
                Plate from level{' '}
                <input
                  type="number"
                  min={1}
                  max={80}
                  placeholder="never"
                  value={shown.plate_from_level}
                  onChange={(event) => change({ plate_from_level: event.target.value })}
                />
              </label>
              <label title="For classes that learn mail at 40 (Hunters, Shamans)">
                Mail from level{' '}
                <input
                  type="number"
                  min={1}
                  max={80}
                  placeholder="never"
                  value={shown.mail_from_level}
                  onChange={(event) => change({ mail_from_level: event.target.value })}
                />
              </label>
              <label title="Weapons ticked under Off hand count from this level (Rogues learn Dual Wield at 10, Warriors and Hunters at 20). Shields and held-in-off-hand items don't need it.">
                Dual wield from level{' '}
                <input
                  type="number"
                  min={1}
                  max={80}
                  placeholder="start"
                  value={shown.dual_wield_from_level}
                  onChange={(event) => change({ dual_wield_from_level: event.target.value })}
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={shown.two_handers}
                  onChange={(event) => change({ two_handers: event.target.checked })}
                />{' '}
                Two-handed weapons
              </label>
              <label title="Include items you can wear within this many levels">
                Levels ahead{' '}
                <input
                  type="number"
                  min={0}
                  max={20}
                  value={shown.levels_ahead}
                  onChange={(event) => change({ levels_ahead: event.target.value })}
                />
              </label>
              <label>
                Upgrades per slot{' '}
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={shown.per_slot}
                  onChange={(event) => change({ per_slot: event.target.value })}
                />
              </label>
              <label title="Score gains at or below this are sidegrades and aren't listed">
                Minimum score gain{' '}
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="0.5"
                  value={shown.min_gain}
                  onChange={(event) => change({ min_gain: event.target.value })}
                />
              </label>
            </div>

            <footer className="weights-actions">
              <button type="submit" disabled={draft === null || typeof parsed === 'string' || busy}>
                {save.isPending ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="secondary" disabled={draft === null} onClick={() => setDraft(null)}>
                Discard
              </button>
              <button type="button" className="secondary" disabled={!view.customised || busy} onClick={() => reset.mutate()}>
                Reset to defaults
              </button>
              {draft !== null && typeof parsed === 'string' && <span className="error">{parsed}</span>}
              {save.isError && <span className="error">{save.error.message}</span>}
              {reset.isError && <span className="error">{reset.error.message}</span>}
            </footer>
          </form>
        )}
      </dialog>
    </>
  )
}
