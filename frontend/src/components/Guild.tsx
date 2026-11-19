import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  api,
  selectedCharacter,
  type AlertKind,
  type GroupDungeon,
  type GuildMember,
  type GuildView,
  type MyGuild,
  type Role,
  type SendResult,
} from '../api'
import { ItemLink } from './ItemLink'

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
          {needs.map((need, i) => (
            <span key={need.item_id}>
              {i > 0 && ', '}
              <ItemLink href={need.wowhead}>{need.item}</ItemLink> (+{need.score_gain.toFixed(1)})
            </span>
          ))}
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
function GuildChannelSection({
  view,
  onSaved,
  as,
}: {
  view: GuildView
  onSaved: (view: GuildView) => void
  as?: number | undefined
}) {
  const [url, setUrl] = useState('')
  const [tested, setTested] = useState<SendResult | null>(null)
  const setChannel = useMutation({
    mutationFn: (next: string) => api.setGuildChannel(next, as),
    onSuccess: (saved) => {
      onSaved(saved)
      setUrl('')
      setTested(null)
    },
  })
  const remove = useMutation({ mutationFn: () => api.removeGuildChannel(as), onSuccess: onSaved })
  const test = useMutation({ mutationFn: () => api.testGuildChannel(as), onSuccess: setTested })
  const share = useMutation({
    mutationFn: (alerts: AlertKind[]) => api.setSharedAlerts(alerts, as),
    onSuccess: onSaved,
  })
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
function GuildPanel({ as }: { as?: number }) {
  const queryClient = useQueryClient()
  const [going, setGoing] = useState<number[] | null>(null)
  const view = useQuery({ queryKey: ['guild', as, going], queryFn: () => api.guild(going ?? undefined, as) })
  const [role, setRole] = useState<Role | null>(null)
  const membership = useMutation({
    mutationFn: ({ optedIn, chosen }: { optedIn: boolean; chosen: Role | null }) =>
      api.setGuildMembership(optedIn, chosen, as),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['guild'] })
      await queryClient.invalidateQueries({ queryKey: ['my-guilds'] })
    },
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
    // A grouped player runs on one character at a time (#215): picking one drops their others.
    const player = data.members.find((m) => m.character_id === id)?.player ?? null
    const others = new Set(
      data.members
        .filter((m) => player !== null && m.player === player && m.character_id !== id)
        .map((m) => m.character_id),
    )
    const next = chosen.has(id) ? data.going.filter((g) => g !== id) : [...data.going.filter((g) => !others.has(g)), id]
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
                  {member.player !== null && (
                    <span className="tag" title="These characters are one player's, who chose to show them so">
                      player {member.player}
                    </span>
                  )}
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
      <GuildChannelSection
        view={data}
        as={as}
        onSaved={(saved) => queryClient.setQueryData(['guild', as, going], saved)}
      />
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

/**
 * Join a guild's view with several of your characters at once, or leave with any one (#215,
 * ADR 0059), optionally sharing the same alerts to the guild's channel for each one joining.
 * Also where you choose to show your characters here as one player. On the Guild tab and the
 * account page.
 */
export function BulkJoin({ guild }: { guild: MyGuild }) {
  const queryClient = useQueryClient()
  const unjoined = guild.characters.filter((c) => !c.joined)
  const [picked, setPicked] = useState<Set<number>>(new Set(unjoined.map((c) => c.id)))
  const [role, setRole] = useState<Role | null>(null)
  const [share, setShare] = useState(false)
  const [alerts, setAlerts] = useState<Set<AlertKind>>(new Set())
  const notifications = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, enabled: share })
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['my-guilds'] })
    await queryClient.invalidateQueries({ queryKey: ['guild'] })
    await queryClient.invalidateQueries({ queryKey: ['account'] })
  }
  const where = { region: guild.region, guild_id: guild.guild_id }
  const change = useMutation({ mutationFn: api.setGuildMembers, onSuccess: refresh })
  const grouping = useMutation({ mutationFn: api.setGuildGrouping, onSuccess: refresh })
  const userAlerts = (notifications.data?.alerts ?? []).filter((a) => a.audience === 'user')
  const joinable = unjoined.filter((c) => picked.has(c.id))
  const failed = change.error ?? grouping.error

  return (
    <div className="bulk-join">
      <ul className="bulk-join-characters">
        {guild.characters.map((character) => (
          <li key={character.id}>
            {character.joined ? (
              <>
                {character.name} <span className="tag done">in the view</span>{' '}
                <button
                  type="button"
                  className="secondary"
                  onClick={() => change.mutate({ ...where, leave: [character.id] })}
                  disabled={change.isPending}
                  aria-label={`Leave the guild view with ${character.name}`}
                >
                  Leave
                </button>
              </>
            ) : (
              <label>
                <input
                  type="checkbox"
                  checked={picked.has(character.id)}
                  onChange={() => {
                    const next = new Set(picked)
                    if (next.has(character.id)) next.delete(character.id)
                    else next.add(character.id)
                    setPicked(next)
                  }}
                />{' '}
                {character.name}
              </label>
            )}
          </li>
        ))}
      </ul>
      {unjoined.length > 0 && (
        <>
          <p>
            <RolePicker value={role} onChange={setRole} />{' '}
            <label>
              <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} /> Also share alerts
              with the guild's channel
            </label>
          </p>
          {share && (
            <fieldset className="share-alerts">
              <legend>Alerts to share, for each one joining</legend>
              {userAlerts.map((alert) => (
                <label key={alert.kind}>
                  <input
                    type="checkbox"
                    checked={alerts.has(alert.kind)}
                    onChange={() => {
                      const next = new Set(alerts)
                      if (next.has(alert.kind)) next.delete(alert.kind)
                      else next.add(alert.kind)
                      setAlerts(next)
                    }}
                  />{' '}
                  {alert.label}
                </label>
              ))}
            </fieldset>
          )}
          <p>
            <button
              type="button"
              disabled={joinable.length === 0 || change.isPending}
              onClick={() =>
                change.mutate({
                  ...where,
                  join: joinable.map((c) => c.id),
                  role,
                  shared_alerts: share ? [...alerts] : null,
                })
              }
            >
              {joinable.length > 1 ? `Join with these ${joinable.length}` : 'Join with this one'}
            </button>
          </p>
        </>
      )}
      {guild.characters.length > 1 && (
        <p>
          <label>
            <input
              type="checkbox"
              checked={guild.grouped}
              disabled={grouping.isPending}
              onChange={(e) => grouping.mutate({ ...where, grouped: e.target.checked })}
            />{' '}
            Show my characters here as one player
          </label>{' '}
          <small className="muted">
            Then only one of them goes at a time, and the group counts you once. Off, nothing the guild sees links them.
          </small>
        </p>
      )}
      {failed && <p className="error">{failed.message}</p>}
    </div>
  )
}

/** Which guild to show first: the selected character's, else the first. */
function startingGuild(guilds: MyGuild[]): number {
  const selected = selectedCharacter()
  const index = guilds.findIndex((g) => g.characters.some((c) => c.id === selected))
  return index >= 0 ? index : 0
}

/** The character to see a guild through: the selected one if it has joined, else a joined one, else any. */
function viewer(guild: MyGuild): number {
  const selected = selectedCharacter()
  const joined = guild.characters.filter((c) => c.joined)
  return (
    joined.find((c) => c.id === selected)?.id ??
    joined[0]?.id ??
    guild.characters.find((c) => c.id === selected)?.id ??
    guild.characters[0]!.id
  )
}

/**
 * The Guild tab (#18, #215): a picker over every guild your characters are in, then the
 * chosen guild's view, seen through one of your characters there, and joining with several.
 */
export function Guild() {
  const mine = useQuery({ queryKey: ['my-guilds'], queryFn: api.myGuilds })
  const [chosen, setChosen] = useState<number | null>(null)
  if (mine.isPending) return <p className="muted">Loading your guilds…</p>
  if (mine.isError) return <p className="error">Couldn't load your guilds: {mine.error.message}</p>
  const guilds = mine.data.guilds
  if (guilds.length === 0) return <GuildPanel />
  const index = Math.min(chosen ?? startingGuild(guilds), guilds.length - 1)
  const guild = guilds[index]!
  return (
    <>
      {guilds.length > 1 && (
        <div className="guild-picker" role="group" aria-label="Your guilds">
          {guilds.map((g, i) => (
            <button
              key={`${g.region}:${g.guild_id}`}
              type="button"
              className={i === index ? '' : 'secondary'}
              aria-pressed={i === index}
              onClick={() => setChosen(i)}
            >
              {g.name}
            </button>
          ))}
        </div>
      )}
      <section>
        <h2>Your characters in {guild.name}</h2>
        <BulkJoin key={`${guild.region}:${guild.guild_id}`} guild={guild} />
      </section>
      <GuildPanel key={`${guild.region}:${guild.guild_id}`} as={viewer(guild)} />
    </>
  )
}
