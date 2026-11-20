import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

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
          What you set in the app: build, gear targets, talent plan, stat weights, rules, dismissed items and class
          quests marked done.
        </li>
        <li>Whether each character's public page is on, and its link's token, until you turn it off.</li>
        <li>The Discord webhooks you add for alerts, and the alerts waiting to be sent.</li>
        <li>A Discord account you link for DMs: its id and name only, until you unlink it.</li>
        <li>
          Game data you import from the CharacterPlannerExport addon: a character's bags, bank and quest log, as of when
          the game saved them. Only the newest import is kept.
        </li>
        <li>
          If you sign in with Battle.net, the sign-in token. With it, the planner can list your account's characters to
          pick from; that list isn't stored, only the characters you pick are tracked.
        </li>
      </ul>
      <p>
        It also caches game data that's the same for every character: items, dungeons, talent trees, and recipes,
        including every recipe of a tracked character's professions, learned or not. Which professions it looks up
        follows from the characters tracked, but the recipes themselves are game data, shared and not tied to anyone.
      </p>

      <h2>How long</h2>
      <p>
        Data from Blizzard is kept for at most 30 days, as Blizzard's terms require; each sync replaces it. The progress
        history and your own settings stay until you delete them. If the operator keeps log files, their lines can name
        the character; the operator decides how long to keep them. If the operator turns on backups, what's set in the
        app (not Blizzard's data) is copied to their storage, encrypted, and the newest few are kept; a deletion reaches
        them once newer backups replace them.
      </p>

      <h2>Who can see it</h2>
      <p>
        Anyone who can open this instance's address. The planner has no accounts of its own, so it's meant for your own
        computer or a private network. Alerts go to the Discord channels you choose, and DMs to the Discord account you
        link: with users on, only about your own characters. With users on, a character you add to its guild's view is
        shown to the other members who joined it: its name, level, spec, role and upgrades. Leave the view to stop that.
        If you have several characters there, you can choose to show them as one player; until you do, nothing the guild
        sees links them. If the guild sets an alert channel, the alerts you choose to share post to that Discord
        channel, for anyone who can read it. With users on, the admin, and any superusers the admin appoints, see a list
        of the accounts: each one's Battle.net account id, role, when it signed up and last signed in, and its
        characters' names. Nothing more of anyone's.
      </p>
      <p>
        If you turn on a character's public page (the Character tab), anyone with its link sees that character, signed in
        or not: its name, level, race, class, guild, spec and talents, equipment, stats and professions, as of the last
        sync. Never your plans, settings, account or other characters. Turning it off, or making a new link, stops the old
        link working at once.
      </p>
      <p>
        With users on, the admin can export everything stored for an account, for an access request, or delete it. A log
        records each deletion, export, role change and enchant correction: who did it, to which account and when, as
        Battle.net account ids, never the data. It stays after the account it names is deleted, as the record the
        request was handled, and its entries are deleted after a year.
      </p>
      <p>An invite link that let you sign up keeps which account used it and when, until 30 days after it was used.</p>

      <h2>Sharing</h2>
      <p>
        Nothing is sold, shared or used for advertising. The planner asks Blizzard's API for the character by name and
        realm, and Forever Companion for items and dungeons by id; neither request carries anything else about you.
      </p>

      <h2>Removing it</h2>
      <p>
        On <a href="#account">My account</a>, remove any of your characters: everything stored for it is deleted and it
        stops being tracked. Other characters and shared game data stay. If it was the only one, the planner tracks the
        character its settings name again on its next start: to stop for good, ask <Contact value={contact} /> to stop
        the planner.
      </p>
      {me.data?.users && (
        <p>
          My account also deletes your whole account: every character you track, with all its data and settings, your
          sign-in and your Battle.net token. The admin can only delete theirs once nobody else uses this instance.
        </p>
      )}
    </article>
  )
}
