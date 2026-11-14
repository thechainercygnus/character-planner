import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import {
  api,
  ApiError,
  selectCharacter,
  selectedCharacter,
  type AccountCharacter,
  type CharacterSummary,
  type NewCharacter,
  type Region,
} from '../api'

const REGIONS: Region[] = ['us', 'eu', 'kr', 'tw']
const ADD = 'add'

function label(character: CharacterSummary): string {
  const name = [character.name, character.surname].filter(Boolean).join(' ')
  const level = character.level === null ? 'not synced' : `level ${character.level}`
  return [name, level, character.character_class].filter(Boolean).join(' · ')
}

function isRegion(value: string): value is Region {
  return (REGIONS as string[]).includes(value)
}

/**
 * The signed-in account's characters not tracked yet, to pick from (#15). Without a
 * Battle.net sign-in, a link to sign in instead.
 */
function FromAccount({ onPick, busy }: { onPick: (character: NewCharacter) => void; busy: boolean }) {
  const account = useQuery({ queryKey: ['account-characters'], queryFn: api.accountCharacters, retry: false })
  if (account.isPending) return <p className="muted">Looking up your Battle.net characters…</p>
  if (account.isError) {
    const signIn = account.error instanceof ApiError && account.error.status === 401
    return signIn ? (
      <p className="muted">
        <a href="/auth/login">Sign in with Battle.net</a> to pick from your characters, or type one in.
      </p>
    ) : (
      <p className="error">Couldn't list your characters: {account.error.message}</p>
    )
  }
  const open = account.data.characters.filter((c: AccountCharacter) => !c.tracked && isRegion(c.region))
  if (open.length === 0) return <p className="muted">Every character on your account is tracked.</p>
  return (
    <ul className="account-characters" aria-label="Your Battle.net characters">
      {open.map((c) => (
        <li key={`${c.region}:${c.slug}`}>
          {[c.name, c.surname].join(' ')} · level {c.level ?? '?'} {c.character_class ?? ''}{' '}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => onPick({ name: c.name, surname: c.surname, region: c.region as Region })}
          >
            Track
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Adds a character to track, then selects and syncs it. */
function AddCharacter({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [surname, setSurname] = useState('')
  const [region, setRegion] = useState<Region>('us')
  const add = useMutation({
    mutationFn: async (character: NewCharacter) => {
      const added = await api.addCharacter(character)
      selectCharacter(added.id)
      await api.sync()
      return added
    },
    onSuccess: async () => {
      onDone()
      await queryClient.resetQueries()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    add.mutate({ name, surname, region })
  }
  return (
    <div className="add-character-panel">
      <FromAccount onPick={(character) => add.mutate(character)} busy={add.isPending} />
      <form className="add-character" onSubmit={submit} aria-label="Add a character">
        <input
          aria-label="First name"
          placeholder="First name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          aria-label="Surname"
          placeholder="Surname"
          value={surname}
          onChange={(e) => setSurname(e.target.value)}
          required
        />
        <select aria-label="Region" value={region} onChange={(e) => setRegion(e.target.value as Region)}>
          {REGIONS.map((r) => (
            <option key={r} value={r}>
              {r.toUpperCase()}
            </option>
          ))}
        </select>
        <button type="submit" disabled={add.isPending}>
          {add.isPending ? 'Adding and syncing…' : 'Add and sync'}
        </button>
        <button type="button" className="secondary" onClick={onDone} disabled={add.isPending}>
          Cancel
        </button>
        {add.isError && <span className="error">Couldn't add it: {add.error.message}</span>}
      </form>
    </div>
  )
}

/**
 * Which character the app shows (#14): every request carries the choice, and switching
 * starts the cache afresh, so nothing of one character shows for another.
 */
export function CharacterSwitcher() {
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['characters'], queryFn: api.characters })
  const [adding, setAdding] = useState(false)
  const characters = list.data?.characters ?? []
  const chosen = selectedCharacter()
  const known = chosen !== null && characters.some((c) => c.id === chosen)

  // A remembered character that's gone (deleted, or another database): back to the default.
  useEffect(() => {
    if (list.data && chosen !== null && !known) {
      selectCharacter(null)
      void queryClient.resetQueries()
    }
  }, [list.data, chosen, known, queryClient])

  if (!list.data || characters.length === 0) return null
  const current = known ? chosen : list.data.default_id

  const change = (value: string) => {
    if (value === ADD) {
      setAdding(true)
      return
    }
    selectCharacter(Number(value))
    void queryClient.resetQueries()
  }

  return (
    <span className="character-switcher">
      <select aria-label="Character" value={adding ? ADD : String(current)} onChange={(e) => change(e.target.value)}>
        {characters.map((character) => (
          <option key={character.id} value={character.id}>
            {label(character)}
          </option>
        ))}
        <option value={ADD}>Add a character…</option>
      </select>
      {adding && <AddCharacter onDone={() => setAdding(false)} />}
    </span>
  )
}
