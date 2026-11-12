import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Candidate } from '../api'

/**
 * Pin and unpin targets (ADR 0014) and dismiss items (ADR 0012), then refresh what
 * shows them: the upgrades, the Plan tab and the target editor.
 */
function useItemChoices() {
  const queryClient = useQueryClient()
  const onSuccess = () =>
    Promise.all(
      ['recommendations', 'gear', 'targets', 'choices'].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      ),
    )
  const pin = useMutation({ mutationFn: api.pinTarget, onSuccess })
  const unpin = useMutation({ mutationFn: api.unpinTarget, onSuccess })
  const dismiss = useMutation({ mutationFn: api.setChoice, onSuccess })
  const undismiss = useMutation({ mutationFn: api.clearChoice, onSuccess })
  const all = [pin, unpin, dismiss, undismiss]
  return {
    pin,
    unpin,
    dismiss,
    undismiss,
    pending: all.some((m) => m.isPending),
    error: all.find((m) => m.isError)?.error,
  }
}

/** "Make target" / "Unpin" and "Never suggest" for one recommended item in a slot. */
export function ChoiceButtons({ candidate, slot }: { candidate: Candidate; slot: string }) {
  const { pin, unpin, dismiss, pending, error } = useItemChoices()
  const { item_id: itemId, name } = candidate.item
  return (
    <div className="choice-buttons">
      {candidate.pinned ? (
        <button type="button" className="link" disabled={pending} onClick={() => unpin.mutate(itemId)}>
          Unpin
        </button>
      ) : (
        <button
          type="button"
          className="link"
          disabled={pending}
          title="Always list it here until you wear it"
          onClick={() => pin.mutate({ itemId, slot })}
        >
          {candidate.is_target ? 'Pin' : 'Make target'}
        </button>
      )}
      <button
        type="button"
        className="link"
        disabled={pending}
        onClick={() => dismiss.mutate({ itemId, name, choice: 'dismissed' })}
      >
        Never suggest
      </button>
      {error && <span className="error">{error.message}</span>}
    </div>
  )
}

/** Items hidden with "Never suggest", each with an undo. Nothing when there are none. */
export function DismissedItems() {
  const choices = useQuery({ queryKey: ['choices'], queryFn: api.choices })
  const { undismiss, pending, error } = useItemChoices()
  const dismissed = (choices.data ?? []).filter((choice) => choice.choice === 'dismissed')
  if (choices.isError) return <p className="error">Couldn't load hidden items: {choices.error.message}</p>
  if (dismissed.length === 0) return null

  return (
    <div className="dismissed">
      <h3>Never suggested</h3>
      <ul>
        {dismissed.map((choice) => (
          <li key={choice.item_id}>
            {choice.name}{' '}
            <button
              type="button"
              className="link"
              disabled={pending}
              aria-label={`Suggest ${choice.name} again`}
              onClick={() => undismiss.mutate(choice.item_id)}
            >
              Undo
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="error">{error.message}</p>}
    </div>
  )
}
