import { useQuery } from '@tanstack/react-query'
import { Fragment } from 'react'
import { api } from '../api'

/**
 * One footer on every page (#43): the Forever Companion credit its terms ask for (a link
 * back, its sources, "fan-made"), and the Source link the AGPL asks a hosted copy to
 * offer (SOURCE_URL points it at a fork).
 */
export function Footer() {
  const about = useQuery({ queryKey: ['about'], queryFn: api.about, staleTime: Infinity })
  if (!about.data) return null
  const { data, source_url, version } = about.data
  return (
    <footer className="page-footer muted">
      <p>
        Item and dungeon data from{' '}
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
        and checked in game by players. Fan-made, not affiliated with Blizzard Entertainment.
      </p>
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
