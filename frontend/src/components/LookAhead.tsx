import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type LookAheadEvent, type LookAheadKind } from '../api'

const STORAGE_KEY = 'look-ahead-levels'
const DEFAULT_LEVELS = 5
const CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

const KIND_LABEL: Record<LookAheadKind, string> = {
  dungeon: 'Dungeon',
  target: 'Gear',
  talent: 'Talent',
  class_quest: 'Quest',
  profession: 'Profession',
}

/** The remembered range: a per-browser convenience, so storage may fail or be empty. */
function storedLevels(): number {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY))
    return CHOICES.includes(value) ? value : DEFAULT_LEVELS
  } catch {
    return DEFAULT_LEVELS
  }
}

function remember(levels: number) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(levels))
  } catch {
    // private window or blocked storage: the choice lasts for this page only
  }
}

function Event({ event }: { event: LookAheadEvent }) {
  const title = event.link ? (
    <a href={event.link} target="_blank" rel="noreferrer">
      {event.title}
    </a>
  ) : (
    event.title
  )
  return (
    <li className={`look-ahead-event kind-${event.kind}`}>
      <span className="look-ahead-kind">{KIND_LABEL[event.kind]}</span>
      <span>
        {title}
        {event.essential && <span className="tag warn">essential</span>}
        {event.pinned && <span className="tag">pinned</span>}
        {event.locked && <span className="tag warn">not open yet</span>}
        {event.detail && <small className="muted">{event.detail}</small>}
      </span>
    </li>
  )
}

/**
 * What each of the next few levels brings (#4): dungeons opening, gear targets coming
 * into reach, talent points, class quests and profession ranks.
 */
export function LookAhead() {
  const [levels, setLevels] = useState(storedLevels)
  const view = useQuery({ queryKey: ['look-ahead', levels], queryFn: () => api.lookAhead(levels) })

  return (
    <section className="look-ahead">
      <div className="section-heading">
        <h2>Coming up</h2>
        <label className="look-ahead-range">
          Next{' '}
          <select
            value={levels}
            onChange={(event) => {
              const value = Number(event.target.value)
              setLevels(value)
              remember(value)
            }}
          >
            {CHOICES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>{' '}
          {levels === 1 ? 'level' : 'levels'}
        </label>
      </div>
      {view.isError && <p className="error">Couldn't load what's coming up: {view.error.message}</p>}
      {view.data && view.data.groups.length === 0 && (
        <p className="muted">
          {view.data.level === null ? 'Sync your character to see what the next levels bring.' : 'Nothing new in these levels.'}
        </p>
      )}
      {view.data?.groups.map((group) => (
        <div key={group.level} className="look-ahead-level">
          <h3>Level {group.level}</h3>
          <ul aria-label={`Level ${group.level}`}>
            {group.events.map((event, i) => (
              <Event key={`${event.kind}:${event.title}:${i}`} event={event} />
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
