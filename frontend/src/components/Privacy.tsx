import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, selectCharacter } from '../api'

const EMAIL = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/

/** The operator's contact as a link when it's an email or web address, else as text. */
export function Contact({ value }: { value: string }) {
  if (!value) return <>the person who runs this instance</>
  if (EMAIL.test(value)) return <a href={`mailto:${value}`}>{value}</a>
  if (/^https?:\/\//.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer">
        {value}
      </a>
    )
  }
  return <>{value}</>
}

/** Deletes everything stored for the character, after a second click to confirm. */
function EraseData() {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const erase = useMutation({
    mutationFn: api.eraseCharacter,
    onSuccess: () => {
      setConfirming(false)
      selectCharacter(null) // it's gone: back to the default character
      return queryClient.invalidateQueries()
    },
  })
  if (erase.isSuccess) {
    const rows = Object.values(erase.data.removed).reduce((sum, n) => sum + n, 0)
    return (
      <p role="status">
        Deleted {rows} stored {rows === 1 ? 'row' : 'rows'}, and stopped tracking the character.
      </p>
    )
  }
  return (
    <div className="erase-data">
      {erase.isError && <p className="error">Couldn't delete the data: {erase.error.message}</p>}
      {confirming ? (
        <>
          <p>
            This stops tracking the character and deletes its snapshots, history, plans and settings. It can't be
            undone.
          </p>
          <button type="button" onClick={() => erase.mutate()} disabled={erase.isPending}>
            {erase.isPending ? 'Deleting…' : 'Yes, delete everything'}
          </button>{' '}
          <button type="button" className="secondary" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" onClick={() => setConfirming(true)}>
          Delete the character's data
        </button>
      )}
    </div>
  )
}

/** With users on (#16): delete the account and everything in it, after a second click. */
function DeleteAccount() {
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
          <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending}>
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
 * The privacy notice (#133): Blizzard's terms ask for one (§2 item 15) and for deletion on
 * request (§11.3, ADR 0034). Every instance is its own licensee, so the contact is the
 * operator's (OPERATOR_CONTACT).
 */
export function Privacy() {
  const about = useQuery({
    queryKey: ['about'],
    queryFn: api.about,
    staleTime: Infinity,
  })
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const contact = about.data?.operator_contact ?? ''
  return (
    <article className="privacy">
      <p>
        <a href="#">← Back to the planner</a>
      </p>
      <h1>Privacy</h1>
      <p>
        This instance of Character Planner is run by <Contact value={contact} />. It plans one World of Warcraft
        character and keeps what it needs in its own database, on the machine it runs on.
      </p>

      <h2>What's stored</h2>
      <ul>
        <li>
          The character's data from Blizzard's Battle.net API: profile, gear, stats, talents, professions and the like,
          fetched at each sync.
        </li>
        <li>A short history for the Progress tab: the date, level and item level of each sync.</li>
        <li>
          What you set in the app: gear targets, talent plan, stat weights, rules, dismissed items and class quests
          marked done.
        </li>
        <li>The Discord webhooks you add for alerts, and the alerts waiting to be sent.</li>
        <li>
          If you sign in with Battle.net, the sign-in token. With it, the planner can list your account's characters to
          pick from; that list isn't stored, only the characters you pick are tracked.
        </li>
      </ul>
      <p>It also caches game data that's the same for every character: items, dungeons, recipes and talent trees.</p>

      <h2>How long</h2>
      <p>
        Data from Blizzard is kept for at most 30 days, as Blizzard's terms require; each sync replaces it. The progress
        history and your own settings stay until you delete them. If the operator keeps log files, their lines can name
        the character; the operator decides how long to keep them.
      </p>

      <h2>Who can see it</h2>
      <p>
        Anyone who can open this instance's address. The planner has no accounts of its own, so it's meant for your own
        computer or a private network. Alerts go to the Discord channels you choose.
      </p>

      <h2>Sharing</h2>
      <p>
        Nothing is sold, shared or used for advertising. The planner asks Blizzard's API for the character by name and
        realm, and Forever Companion for items and dungeons by id; neither request carries anything else about you.
      </p>

      <h2>Removing it</h2>
      <p>
        Delete everything stored for the character you're viewing here: it stops being tracked. Other characters and
        shared game data stay. If it's the only one, the planner tracks the character its settings name again on its
        next start: to stop for good, ask <Contact value={contact} /> to stop the planner.
      </p>
      <EraseData />
      {me.data?.users && me.data.signed_in && (
        <>
          <h2>Your account</h2>
          <p>
            Delete your account and everything stored for you. The admin can only delete theirs once nobody else uses
            this instance.
          </p>
          <DeleteAccount />
        </>
      )}
    </article>
  )
}
