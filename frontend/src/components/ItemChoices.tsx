import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Candidate, type ItemChoice } from '../api'

/** Pin, unpin, dismiss and un-dismiss items; refreshes the lists that use them (ADR 0012). */
function useItemChoices() {
  const queryClient = useQueryClient()
  const onSuccess = (choices: ItemChoice[]) => {
    queryClient.setQueryData(['choices'], choices)
    return queryClient.invalidateQueries({ queryKey: ['recommendations'] })
  }
  const set = useMutation({ mutationFn: api.setChoice, onSuccess })
  const clear = useMutation({ mutationFn: api.clearChoice, onSuccess })
  return { set, clear, pending: set.isPending || clear.isPending, error: set.error ?? clear.error }
}

/** "Make target" / "Unpin" and "Never suggest" for one recommended item. */
export function ChoiceButtons({ candidate }: { candidate: Candidate }) {
  const { set, clear, pending, error } = useItemChoices()
  const { item_id: itemId, name } = candidate.item
  return (
    <div className="choice-buttons">
      {candidate.pinned ? (
        <button type="button" className="link" disabled={pending} onClick={() => clear.mutate(itemId)}>
          Unpin
        </button>
      ) : candidate.is_target ? null : ( // already a target in gear_targets.yaml
        <button
          type="button"
          className="link"
          disabled={pending}
          onClick={() => set.mutate({ itemId, name, choice: 'target' })}
        >
          Make target
        </button>
      )}
      <button
        type="button"
        className="link"
        disabled={pending}
        onClick={() => set.mutate({ itemId, name, choice: 'dismissed' })}
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
  const { clear, pending, error } = useItemChoices()
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
              onClick={() => clear.mutate(choice.item_id)}
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
