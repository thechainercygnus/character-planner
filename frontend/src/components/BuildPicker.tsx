import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type BuildSummary } from '../api'

const ROLE_LABEL = { tank: 'tank', healer: 'healer', dps: 'DPS' } as const

function describe(build: BuildSummary): string {
  return [
    `${ROLE_LABEL[build.role]}`,
    `${build.preset_name} weights`,
    build.talents ? `${build.spec} talents` : 'no talent order yet',
  ].join(' · ')
}

/**
 * Pick the build a character follows (#216, ADR 0060): its weight preset, talent order and
 * guild role, set together. Each piece can still be edited, and shows here as customised.
 * On the Character tab for the selected character, and on My account for each one (`as`).
 */
export function BuildPicker({ as, label }: { as?: number; label: string }) {
  const queryClient = useQueryClient()
  const view = useQuery({ queryKey: ['builds', as ?? null], queryFn: () => api.builds(as) })
  const [picked, setPicked] = useState<string | null>(null)
  const choose = useMutation({
    mutationFn: (key: string | null) => api.setBuild(key, as),
    onSuccess: async (saved) => {
      queryClient.setQueryData(['builds', as ?? null], saved)
      setPicked(null)
      // Its weights and talent plan changed: everything scored from them too.
      await queryClient.invalidateQueries()
    },
  })
  if (view.isError) return <p className="error">Couldn't load builds: {view.error.message}</p>
  if (!view.data) return null
  const data = view.data
  const current = data.builds.find((b) => b.key === data.current) ?? null
  const choice = picked ?? data.current ?? ''
  const pending = data.builds.find((b) => b.key === choice) ?? null
  const changing = choice !== (data.current ?? '')

  return (
    <div className="build-picker">
      <label>
        {label}{' '}
        <select value={choice} onChange={(event) => setPicked(event.target.value)} disabled={choose.isPending}>
          <option value="">None</option>
          {data.builds.map((build) => (
            <option key={build.key} value={build.key}>
              {build.name}
            </option>
          ))}
        </select>
      </label>{' '}
      {changing && (
        <button type="button" onClick={() => choose.mutate(choice || null)} disabled={choose.isPending}>
          {choice ? 'Follow this build' : 'Stop following it'}
        </button>
      )}
      {pending && <small className="muted"> {describe(pending)}</small>}
      {changing && pending?.talents && <small className="warn"> Its talent order replaces the talent plan.</small>}
      {!changing && current && data.customised.length > 0 && (
        <small className="muted">
          {' '}
          Customised since:{' '}
          {data.customised.map((piece) => (piece === 'weights' ? 'stat weights' : 'talent plan')).join(' and ')}. Follow
          it again to reset the talent plan.
        </small>
      )}
      {choose.isError && <small className="error"> {choose.error.message}</small>}
    </div>
  )
}
