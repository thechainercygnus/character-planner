import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type GuestQuery } from '../api'
import { Dungeons } from './Dungeons'
import { Recommendations } from './Recommendations'

/** Guest mode (ADR 0017): pick a class and level, see the best items and dungeons. */
export function GuestMode() {
  const options = useQuery({ queryKey: ['guest'], queryFn: api.guest })
  const [levelText, setLevelText] = useState('15')
  const [classKey, setClassKey] = useState('warrior')
  const [faction, setFaction] = useState('alliance')
  const [preset, setPreset] = useState<string | null>(null)

  const level = Number(levelText)
  const validLevel = Number.isInteger(level) && level >= 1 && level <= 80
  const chosenPreset = preset ?? options.data?.presets[0]?.key ?? ''
  const query: GuestQuery = { classKey, level, faction, preset: chosenPreset }
  const recommendations = useQuery({
    queryKey: ['guest-recommendations', query],
    queryFn: () => api.guestRecommendations(query),
    enabled: validLevel && options.isSuccess,
  })

  if (options.isError) return <p className="error">Couldn't load guest mode: {options.error.message}</p>
  if (!options.data) return <p className="muted">Loading guest mode…</p>

  return (
    <section className="guest-mode">
      <h2>Try it without an account</h2>
      <p className="muted">
        Pick a class and a level to see the best item for each slot from dungeon drops and quest rewards, and which
        dungeons hold the most of them. Nothing you pick here is saved.
      </p>
      <div className="guest-form">
        <label>
          Class{' '}
          <select value={classKey} onChange={(event) => setClassKey(event.target.value)}>
            {options.data.classes.map((c) => (
              <option key={c.key} value={c.key}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Level{' '}
          <input
            type="number"
            min={1}
            max={80}
            value={levelText}
            onChange={(event) => setLevelText(event.target.value)}
          />
        </label>
        <label>
          Faction{' '}
          <select value={faction} onChange={(event) => setFaction(event.target.value)}>
            {options.data.factions.map((f) => (
              <option key={f} value={f}>
                {f[0].toUpperCase() + f.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Play style{' '}
          <select value={chosenPreset} onChange={(event) => setPreset(event.target.value)}>
            {options.data.presets.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {options.data.classes.length === 1 && (
        <p className="muted">
          Only {options.data.classes[0].name} has gear rules so far; more classes are coming.
        </p>
      )}
      {!validLevel && <p className="error">Level must be a whole number from 1 to 80.</p>}
      {recommendations.isPending && validLevel && <p className="muted">Finding items…</p>}
      {recommendations.isError && <p className="error">Couldn't load items: {recommendations.error.message}</p>}
      {recommendations.data && (
        <>
          <Recommendations data={recommendations.data} guest />
          <Dungeons data={recommendations.data} />
        </>
      )}
    </section>
  )
}

/** Shown when there's no character data yet: what the planner does and how to start. */
export function Landing({ hasCharacter = false }: { hasCharacter?: boolean }) {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const sync = useMutation({ mutationFn: api.sync, onSuccess: () => queryClient.invalidateQueries() })
  const loggedIn = status.data?.logged_in ?? false

  return (
    <div className="landing">
      {hasCharacter ? (
        <p>
          <a href="#upgrades">← Back to your character</a>
        </p>
      ) : (
        <section className="landing-intro">
          <h1>Plan your WoW Forever character</h1>
          <p>
            The planner reads your character from Battle.net and works out what to do next: the gear upgrades in reach
            from dungeons and quests, the dungeons worth running, enchants to look for, and how your talents and gear
            compare with your plan.
          </p>
          <ul className="landing-tabs">
            <li>
              <strong>Upgrades</strong> – the best items for each slot, scored against what you wear, plus enchants.
            </li>
            <li>
              <strong>Dungeons</strong> – which dungeons hold the most upgrades for you.
            </li>
            <li>
              <strong>Plan</strong> – your gear targets per slot: what to go for now and what's coming up.
            </li>
            <li>
              <strong>Progress</strong> – level, item level and gear score over time, from each sync.
            </li>
            <li>
              <strong>Character</strong> – your talents against a plan, equipment, stats and professions.
            </li>
          </ul>

          <h2>Get your character in</h2>
          {loggedIn ? (
            <>
              <p>You're logged in, but nothing has been synced yet.</p>
              <p>
                <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}>
                  {sync.isPending ? 'Syncing…' : 'Sync now'}
                </button>
              </p>
              {sync.isError && <p className="error">Sync failed: {sync.error.message}</p>}
            </>
          ) : (
            <ol>
              <li>
                <a className="button" href="/auth/login">
                  Log in with Battle.net
                </a>
              </li>
              <li>Sync, to pull your character's profile, gear, talents and professions.</li>
            </ol>
          )}
          <p className="muted">
            The planner only asks to read your profile. What it reads is kept as snapshots on this server, so it can
            show your progress over time; it never changes anything in the game or on your account.
          </p>
        </section>
      )}
      <GuestMode />
    </div>
  )
}
