import { parseUtc, slotLabel, type Progress as ProgressData, type ProgressPoint } from '../api'
import { LineChart, type ChartPoint } from './LineChart'
import { signed } from '../format'

type Measure = {
  key: keyof Omit<ProgressPoint, 'captured_at'>
  label: string
  digits: number
}

const MEASURES: Measure[] = [
  { key: 'level', label: 'Level', digits: 0 },
  { key: 'item_level', label: 'Item level', digits: 1 },
  { key: 'gear_score', label: 'Gear score', digits: 1 },
  { key: 'health', label: 'Health', digits: 0 },
  { key: 'armor', label: 'Armor', digits: 0 },
  { key: 'stamina', label: 'Stamina', digits: 0 },
]

const dateFormat = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

function series(points: ProgressPoint[], key: Measure['key']): ChartPoint[] {
  return points.flatMap((point) => {
    const value = point[key]
    return value === null ? [] : [{ at: parseUtc(point.captured_at), value }]
  })
}

function Tile({ measure, data }: { measure: Measure; data: ChartPoint[] }) {
  const first = data[0]
  const last = data[data.length - 1]
  const change = last.value - first.value
  return (
    <div className="tile">
      <span className="muted">{measure.label}</span>
      <strong>{last.value.toFixed(measure.digits)}</strong>
      <small className={change > 0 ? 'gains' : 'muted'}>
        {change === 0 ? 'no change' : signed(change, measure.digits)} since {dateFormat.format(first.at)}
      </small>
    </div>
  )
}

type LogEntry = { at: Date; key: string; text: string; gain: number | null }

/** Level, item level, gear score and survivability over time, from every sync (ADR 0008). */
export function Progress({ data }: { data: ProgressData }) {
  if (data.points.length === 0) {
    return (
      <section>
        <h2>Progress</h2>
        <p className="muted">No syncs yet. Every sync adds a point here.</p>
      </section>
    )
  }

  const measures = MEASURES.map((measure) => ({ measure, data: series(data.points, measure.key) })).filter(
    (entry) => entry.data.length > 0,
  )
  const log: LogEntry[] = [
    ...data.level_ups.map((up) => ({
      at: parseUtc(up.captured_at),
      key: `level-${up.level}`,
      text: `Reached level ${up.level}`,
      gain: null,
    })),
    ...data.gear_changes.map((change) => ({
      at: parseUtc(change.captured_at),
      key: `${change.captured_at}-${change.slot}`,
      text: `${slotLabel(change.slot)}: ${change.before ?? 'empty'} → ${change.after ?? 'removed'}`,
      gain: change.score_change,
    })),
  ].sort((a, b) => b.at.getTime() - a.at.getTime())

  return (
    <section>
      <h2>
        Progress{' '}
        <span className="muted">
          {data.points.length} sync{data.points.length === 1 ? '' : 's'} since{' '}
          {dateFormat.format(parseUtc(data.points[0].captured_at))}
        </span>
      </h2>
      {data.points.length < 3 && (
        <p className="muted">Sync after each play session to build up the history.</p>
      )}

      <div className="tiles">
        {measures.map(({ measure, data: points }) => (
          <Tile key={measure.key} measure={measure} data={points} />
        ))}
      </div>

      <div className="charts">
        {measures.map(({ measure, data: points }) => (
          <LineChart
            key={measure.key}
            title={measure.label}
            points={points}
            format={(value) => value.toFixed(measure.digits)}
          />
        ))}
      </div>

      <h3>Changes</h3>
      {log.length === 0 ? (
        <p className="muted">No gear swaps or level-ups between syncs yet.</p>
      ) : (
        <ul className="change-log">
          {log.map((entry) => (
            <li key={entry.key}>
              <span className="muted">{dateTimeFormat.format(entry.at)}</span>
              <span>{entry.text}</span>
              {entry.gain !== null && (
                <span className={entry.gain > 0 ? 'gain' : 'muted'}>{signed(entry.gain, 1)}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <details className="data-table">
        <summary>Show as table</summary>
        <table className="gear">
          <thead>
            <tr>
              <th>Synced</th>
              {MEASURES.map((measure) => (
                <th key={measure.key}>{measure.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.points.map((point) => (
              <tr key={point.captured_at}>
                <td>{dateTimeFormat.format(parseUtc(point.captured_at))}</td>
                {MEASURES.map((measure) => {
                  const value = point[measure.key]
                  return <td key={measure.key}>{value === null ? '–' : value.toFixed(measure.digits)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}
