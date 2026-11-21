import { ResponsiveTable } from './ResponsiveTable'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, isQueued, selectCharacter, selectedCharacter, type MyCharacter } from '../api'
import { ago, parseTime } from '../gameData'
import { BuildPicker } from './BuildPicker'
import { AddCharacter } from './CharacterSwitcher'
import { DiscordSettings } from './DiscordDialog'
import { BulkJoin } from './Guild'
import { NotificationsForm } from './NotificationsDialog'

function when(timestamp: string | null): string {
  return timestamp ? ago(parseTime(timestamp)) : 'never'
}

/** Stop tracking a character and delete everything stored for it, after a second click. */
function RemoveCharacter({ character }: { character: MyCharacter }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: () => api.removeCharacter(character.id),
    onSuccess: async () => {
      setConfirming(false)
      if (selectedCharacter() === character.id) selectCharacter(null) // it's gone
      await queryClient.invalidateQueries()
    },
  })
  if (!confirming) {
    return (
      <button type="button" className="secondary" onClick={() => setConfirming(true)}>
        Remove…
      </button>
    )
  }
  return (
    <span className="confirm-remove">
      Delete {character.name} and everything stored for it?{' '}
      <button type="button" className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
        {remove.isPending ? 'Deleting…' : 'Yes, remove it'}
      </button>{' '}
      <button type="button" className="secondary" onClick={() => setConfirming(false)}>
        Cancel
      </button>
      {remove.isError && <small className="error"> {remove.error.message}</small>}
    </span>
  )
}

function SyncCharacter({ character }: { character: MyCharacter }) {
  const queryClient = useQueryClient()
  const sync = useMutation({
    mutationFn: () => api.syncCharacter(character.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['account'] }),
  })
  return (
    <>
      <button
        type="button"
        className="secondary"
        onClick={() => sync.mutate()}
        disabled={sync.isPending}
        aria-label={`Sync ${character.name}`}
      >
        {sync.isPending ? 'Syncing…' : 'Sync'}
      </button>
      {sync.data && isQueued(sync.data) && <small className="muted"> queued</small>}
      {sync.isError && <small className="error"> {sync.error.message}</small>}
    </>
  )
}

function Characters({ characters }: { characters: MyCharacter[] }) {
  const [adding, setAdding] = useState(false)
  return (
    <section>
      <h2>Characters</h2>
      {characters.length === 0 && <p className="muted">No characters yet.</p>}
      {characters.length > 0 && (
        <ResponsiveTable caption="My characters" className="my-characters">
          <thead>
            <tr>
              <th scope="col">Character</th>
              <th scope="col">Build</th>
              <th scope="col">Last sync</th>
              <th scope="col">Guild</th>
              <th scope="col">Game data</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {characters.map((character) => (
              <tr key={character.id}>
                <th scope="row">
                  <strong>{character.name}</strong>{' '}
                  <span className="muted">
                    {[
                      character.level !== null ? `level ${character.level}` : null,
                      character.character_class,
                      character.region.toUpperCase(),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {character.default && <span className="tag">default</span>}
                </th>
                <td data-label="Build">
                  <BuildPicker as={character.id} label={`Build for ${character.name}`} />
                </td>
                <td data-label="Last sync">{when(character.last_sync)}</td>
                <td data-label="Guild">
                  {character.guild ?? <span className="muted">none</span>}
                  {character.in_guild_view && <span className="tag done">in the guild view</span>}
                </td>
                <td data-label="Game data">{character.game_data_at ? `from the game, ${when(character.game_data_at)}` : 'none'}</td>
                <td className="row-actions" data-label="Actions">
                  <SyncCharacter character={character} /> <RemoveCharacter character={character} />
                </td>
              </tr>
            ))}
          </tbody>
        </ResponsiveTable>
      )}
      {adding ? (
        <AddCharacter onDone={() => setAdding(false)} />
      ) : (
        <p>
          <button type="button" className="secondary" onClick={() => setAdding(true)}>
            Add a character
          </button>
        </p>
      )}
    </section>
  )
}

/**
 * The guilds your characters are in. With users on, join or leave each guild's view with
 * several at once, and choose whether they show as one player (#215); without users there's
 * no guild view, so just which guild each is in.
 */
function Guilds({ characters, users }: { characters: MyCharacter[]; users: boolean }) {
  const mine = useQuery({ queryKey: ['my-guilds'], queryFn: api.myGuilds, enabled: users })
  if (users) {
    if (mine.isError) return <p className="error">Couldn't load your guilds: {mine.error.message}</p>
    const guilds = mine.data?.guilds ?? []
    if (guilds.length === 0) return null
    return (
      <section>
        <h2>Guilds</h2>
        {guilds.map((guild) => (
          <div key={`${guild.region}:${guild.guild_id}`} className="my-guild">
            <h3>{guild.name}</h3>
            <BulkJoin guild={guild} />
          </div>
        ))}
        <p className="muted">
          The <a href="#guild">Guild tab</a> shows who needs what, and the runs worth most to the group.
        </p>
      </section>
    )
  }
  const guilds = new Map<string, MyCharacter[]>()
  for (const character of characters) {
    if (character.guild) guilds.set(character.guild, [...(guilds.get(character.guild) ?? []), character])
  }
  if (guilds.size === 0) return null
  return (
    <section>
      <h2>Guilds</h2>
      <ul className="my-guilds">
        {[...guilds].map(([guild, members]) => (
          <li key={guild}>
            <strong>{guild}</strong>: {members.map((m) => m.name).join(', ')}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** With users on (#16): delete the account and everything in it, after a second click. */
export function DeleteAccount() {
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: api.deleteAccount,
    onSuccess: () => {
      selectCharacter(null)
      window.location.assign('/')
    },
  })
  return (
    <div className="erase-data">
      {remove.isError && <p className="error">{remove.error.message}</p>}
      {confirming ? (
        <>
          <p>
            This deletes your account: every character you track, with all its data and settings, your sign-in and your
            Battle.net token. It can't be undone.
          </p>
          <button type="button" className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending ? 'Deleting…' : 'Yes, delete my account'}
          </button>{' '}
          <button type="button" className="secondary" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" onClick={() => setConfirming(true)}>
          Delete my account
        </button>
      )}
    </div>
  )
}

/**
 * My account (#217, ADR 0058): your characters, guilds, alerts and data in one place, outside
 * the character tabs. Without users it's the one person's: no sign-in, no account to delete.
 */
export function Account() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const view = useQuery({ queryKey: ['account'], queryFn: api.account })
  const discord = useQuery({ queryKey: ['discord'], queryFn: api.discord })
  const signOut = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      selectCharacter(null)
      window.location.assign('/')
    },
  })
  const data = view.data
  // System alerts are the admin's with users on (#164); everyone's without.
  const admin = !me.data?.users || me.data.admin
  return (
    <article className="account">
      <p>
        <a href="#">← Back to the planner</a>
      </p>
      <h1>My account</h1>
      {view.isError && <p className="error">Couldn't load your account: {view.error.message}</p>}
      {data && (
        <>
          <Characters characters={data.characters} />
          <Guilds characters={data.characters} users={data.users} />

          <section>
            <h2>Alerts</h2>
            <NotificationsForm admin={admin} />
            {discord.data?.available && (
              <>
                <h3>Discord DMs</h3>
                <DiscordSettings />
              </>
            )}
          </section>

          <section>
            <h2>Your data</h2>
            <p>
              Everything stored for {data.users ? 'your account' : 'this instance'}, as JSON in a zip: your characters'
              data and settings, and your alert destinations (webhook addresses masked).
            </p>
            <p>
              <a className="button secondary" href={api.exportMineUrl} download>
                Download my data
              </a>
            </p>
            <p className="muted">
              Remove a single character above. <a href="#privacy">Privacy</a> says what's stored and for how long.
            </p>
            {data.users && <DeleteAccount />}
          </section>

          {data.users && data.account_id !== null && (
            <section>
              <h2>Sign-in</h2>
              <p>
                Signed in with Battle.net account {data.account_id}
                {data.role && data.role !== 'user' ? ` (${data.role})` : ''}.{' '}
                <button
                  type="button"
                  className="secondary"
                  onClick={() => signOut.mutate()}
                  disabled={signOut.isPending}
                >
                  Sign out
                </button>
              </p>
            </section>
          )}
        </>
      )}
    </article>
  )
}
