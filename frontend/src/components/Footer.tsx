import { useQuery } from '@tanstack/react-query'
import { Fragment } from 'react'
import { api } from '../api'

/** Blizzard's developer portal: where the Battle.net API's data comes from. */
export const BATTLE_NET_API = 'https://develop.battle.net/'

/**
 * One footer on every page:
 * - Blizzard named as the source of character and game data, as its API terms require
 *   (§2 item 13, ADR 0034, #132);
 * - the Forever Companion credit its terms ask for (a link back, its sources, #43);
 * - "fan-made", and the Source link the AGPL asks a hosted copy to offer (SOURCE_URL
 *   points it at a fork).
 */
export function Footer() {
  const about = useQuery({ queryKey: ['about'], queryFn: api.about, staleTime: Infinity })
  if (!about.data) return null
  const { data, source_url, version } = about.data
  return (
    <footer className="page-footer muted">
      <p>
        Character and game data from{' '}
        <a href={BATTLE_NET_API} target="_blank" rel="noreferrer">
          Blizzard Entertainment's Battle.net API
        </a>
        . Item and dungeon data from{' '}
        <a href={data.url} target="_blank" rel="noreferrer">
          {data.name}
        </a>
        , gathered from{' '}
        {data.sources.map((source, i) => (
          <Fragment key={source.url}>
            {i > 0 && (i === data.sources.length - 1 ? ' and ' : ', ')}
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.name}
            </a>
          </Fragment>
        ))}{' '}
        and checked in game by players.
      </p>
      <p>Fan-made, not affiliated with or endorsed by Blizzard Entertainment.</p>
      <p>
        Character Planner {version} ·{' '}
        <a href={source_url} target="_blank" rel="noreferrer">
          Source
        </a>{' '}
        (AGPL-3.0)
      </p>
    </footer>
  )
}
