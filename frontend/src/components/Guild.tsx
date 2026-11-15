import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  api,
  type AlertKind,
  type GroupDungeon,
  type GuildMember,
  type GuildView,
  type Role,
  type SendResult,
} from '../api'

const ROLE_LABEL: Record<Role, string> = { tank: 'Tank', healer: 'Healer', dps: 'DPS' }

function RolePicker({ value, onChange }: { value: Role | null; onChange: (role: Role | null) => void }) {
  return (
    <select
      aria-label="Your role"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : (e.target.value as Role))}
    >
      <option value="">From my spec</option>
      <option value="tank">Tank</option>
      <option value="healer">Healer</option>
      <option value="dps">DPS</option>
    </select>
  )
}

function Needs({ dungeon, members }: { dungeon: GroupDungeon; members: GuildMember[] }) {
  const names = new Map(members.map((m) => [m.character_id, m.name]))
  return (
    <ul className="guild-needs">
      {Object.entries(dungeon.needs).map(([id, needs]) => (
        <li key={id}>
          <strong>{names.get(Number(id)) ?? 'A member'}</strong>
          {!dungeon.in_range.includes(Number(id)) && <span className="muted"> (outside its levels)</span>}:{' '}
          {needs.map((need) => `${need.item} (+${need.score_gain.toFixed(1)})`).join(', ')}
        </li>
      ))}
    </ul>
  )
}

function when(timestamp: string): string {
  // Backend timestamps are UTC without an offset.
  return new Date(timestamp.endsWith('Z') || timestamp.includes('+') ? timestamp : `${timestamp}Z`).toLocaleString()
}

/**
 * The guild's alert channel (#163, ADR 0046): any member sets its Discord webhook, and
 * each member ticks which of their own alerts post there. Nothing posts until they do.
 */
function GuildChannelSection({ view, onSaved }: { view: GuildView; onSaved: (view: GuildView) => void }) {
  const [url, setUrl] = useState('')
  const [tested, setTested] = useState<SendResult | null>(null)
  const setChannel = useMutation({
    mutationFn: api.setGuildChannel,
    onSuccess: (saved) => {
      onSaved(saved)
      setUrl('')
      setTested(null)
    },
  })
  const remove = useMutation({ mutationFn: api.removeGuildChannel, onSuccess: onSaved })
  const test = useMutation({ mutationFn: api.testGuildChannel, onSuccess: setTested })
  const share = useMutation({ mutationFn: api.setSharedAlerts, onSuccess: onSaved })
  const channel = view.channel
  const shared = view.shared_alerts ?? []
  const busy = setChannel.isPending || remove.isPending || test.isPending || share.isPending
  const error = setChannel.error ?? remove.error ?? test.error ?? share.error

  return (
    <section className="guild-channel">
      <h2>Guild alert channel</h2>
      <p className="muted">
        A Discord channel for the guild: members choose which of their own alerts post there. Everyone who can read that
        channel sees them, so share only what you're happy to.
      </p>
      {channel ? (
        <p>
          Posting to <span className="muted">{channel.url}</span>, set by {channel.set_by ?? 'a former member'} on{' '}
          {when(channel.set_at)}.{' '}
          <button type="button" className="secondary" disabled={busy} onClick={() => test.mutate()}>
            {test.isPending ? 'Sending…' : 'Send a test'}
          </button>{' '}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  'Remove the guild channel? Nobody in the guild gets alerts there until one is set again.',
                )
              )
                remove.mutate()
            }}
          >
            Remove
          </button>
          {tested?.ok && <span className="muted"> Test sent.</span>}
          {tested && !tested.ok && <span className="error"> Test failed: {tested.error}</span>}
          {!tested && channel.last_error && <span className="error"> Last error: {channel.last_error}</span>}
        </p>
      ) : (
        <p className="muted">No channel yet.</p>
      )}
      <form
        className="add-destination"
        onSubmit={(event) => {
          event.preventDefault()
          setChannel.mutate(url)
        }}
      >
        <label>
          {channel ? 'Replace with a webhook' : 'Channel webhook URL'}{' '}
          <input
            value={url}
            autoComplete="off"
            spellCheck={false}
            placeholder="https://discord.com/api/webhooks/…"
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy || !url.trim()}>
          {channel ? 'Replace' : 'Set'}
        </button>
      </form>
      <fieldset className="rule-types">
        <legend>Share my alerts there</legend>
        {(view.alerts ?? []).map((alert) => (
          <label key={alert.kind}>
            <input
              type="checkbox"
              checked={shared.includes(alert.kind)}
              disabled={busy}
              onChange={(event) =>
                share.mutate(
                  event.target.checked ? [...shared, alert.kind] : shared.filter((k: AlertKind) => k !== alert.kind),
                )
              }
            />{' '}
            {alert.label}
          </label>
        ))}
      </fieldset>
      {error && <p className="error">{error.message}</p>}
    </section>
  )
}

/**
 * The guild view (#18, ADR 0042): opted-in members of the character's guild, their roles,
 * and the dungeons worth most to the members going. Nothing about anyone shows until this
 * character opts in.
 */
export function Guild() {
  const queryClient = useQueryClient()
  const [going, setGoing] = useState<number[] | null>(null)
  const view = useQuery({ queryKey: ['guild', going], queryFn: () => api.guild(going ?? undefined) })
  const [role, setRole] = useState<Role | null>(null)
  const membership = useMutation({
    mutationFn: ({ optedIn, chosen }: { optedIn: boolean; chosen: Role | null }) =>
      api.setGuildMembership(optedIn, chosen),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['guild'] }),
  })

  if (view.isPending) return <p className="muted">Loading the guild…</p>
  if (view.isError) return <p className="error">Couldn't load the guild: {view.error.message}</p>
  const data = view.data
  if (!data.guild) return <p className="muted">This character isn't in a guild. Sync after joining one.</p>

  if (!data.opted_in) {
    return (
      <section className="guild">
        <h2>{data.guild.name}</h2>
        <p>
          Plan dungeon runs with guildmates: who needs what, and which dungeon is worth most to the group. Only members
          who join see it, and they see each other's characters, levels and upgrades.
        </p>
        <p>
          <RolePicker value={role} onChange={setRole} />{' '}
          <button
            type="button"
            onClick={() => membership.mutate({ optedIn: true, chosen: role })}
            disabled={membership.isPending}
          >
            Join the guild view
          </button>
        </p>
        {membership.isError && <p className="error">{membership.error.message}</p>}
      </section>
    )
  }

  const chosen = new Set(data.going)
  const toggle = (id: number) => {
    const next = chosen.has(id) ? data.going.filter((g) => g !== id) : [...data.going, id]
    setGoing(next)
  }

  return (
    <>
      <section className="guild">
        <h2>{data.guild.name}</h2>
        <p>
          Your role:{' '}
          <RolePicker value={data.role} onChange={(next) => membership.mutate({ optedIn: true, chosen: next })} />{' '}
          <button
            type="button"
            className="secondary"
            onClick={() => membership.mutate({ optedIn: false, chosen: null })}
            disabled={membership.isPending}
          >
            Leave the guild view
          </button>
        </p>
        <table className="gear guild-members">
          <thead>
            <tr>
              <th>Going</th>
              <th>Member</th>
              <th>Level</th>
              <th>Spec</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((member) => (
              <tr key={member.character_id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${member.name} is going`}
                    checked={chosen.has(member.character_id)}
                    // At least one goes: an empty group would mean everyone again.
                    disabled={chosen.has(member.character_id) && data.going.length === 1}
                    onChange={() => toggle(member.character_id)}
                  />
                </td>
                <td>
                  {member.name}
                  {member.yours && <span className="muted"> (yours)</span>}
                </td>
                <td>{member.level ?? '?'}</td>
                <td>{[member.spec, member.character_class].filter(Boolean).join(' ') || '?'}</td>
                <td>{member.role ? ROLE_LABEL[member.role] : '?'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.missing_roles.length > 0 && (
          <p className="warn" role="status">
            No {data.missing_roles.map((r) => ROLE_LABEL[r].toLowerCase()).join(' or ')} among the members going.
          </p>
        )}
      </section>
      <GuildChannelSection view={data} onSaved={(saved) => queryClient.setQueryData(['guild', going], saved)} />
      <section>
        <h2>Best runs for the group</h2>
        {data.dungeons.length === 0 ? (
          <p className="muted">No dungeon has upgrades for the members going.</p>
        ) : (
          <ol className="guild-dungeons">
            {data.dungeons.map((dungeon) => (
              <li key={dungeon.dungeon_id}>
                <details>
                  <summary>
                    <strong>{dungeon.dungeon}</strong>{' '}
                    <span className="muted">
                      levels {dungeon.min_level ?? '?'}–{dungeon.max_level ?? '?'} · +{dungeon.total_gain.toFixed(1)} ·{' '}
                      {dungeon.in_range.length} of {data.going.length} in range
                    </span>
                  </summary>
                  <Needs dungeon={dungeon} members={data.members} />
                </details>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  )
}
