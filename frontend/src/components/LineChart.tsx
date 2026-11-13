import { useState } from 'react'

export interface ChartPoint {
  at: Date
  value: number
}

const WIDTH = 320
const HEIGHT = 140
const PAD = { top: 12, right: 14, bottom: 22, left: 40 }

function domain(values: number[]): [number, number] {
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return [min - 1, max + 1] // flat line: give it room
  const pad = (max - min) * 0.1
  return [min - pad, max + pad]
}

const dateFormat = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

// A default prop made once, not on every render (oxlint react/no-object-type-as-default-prop).
function plainNumber(value: number): string {
  return String(value)
}

/**
 * One measure over time: 2px line, 8px markers, recessive axes, and a hover crosshair
 * with the value. Single series, so no legend: the title names it.
 */
export function LineChart({
  title,
  points,
  format = plainNumber,
}: {
  title: string
  points: ChartPoint[]
  format?: (value: number) => string
}) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length === 0) return null

  const times = points.map((p) => p.at.getTime())
  const t0 = Math.min(...times)
  const t1 = Math.max(...times)
  const [v0, v1] = domain(points.map((p) => p.value))
  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const x = (t: number) => PAD.left + (t1 === t0 ? plotW / 2 : ((t - t0) / (t1 - t0)) * plotW)
  const y = (v: number) => PAD.top + plotH - ((v - v0) / (v1 - v0)) * plotH
  const coords = points.map((p) => [x(p.at.getTime()), y(p.value)] as const)
  const line = coords.map(([cx, cy]) => `${cx},${cy}`).join(' ')
  const latest = points[points.length - 1]
  const active = hover === null ? null : points[hover]
  const activeXY = hover === null ? null : coords[hover]

  // Hit targets: each point owns the band halfway to its neighbours.
  const bands = coords.map(([cx], index) => {
    const left = index === 0 ? PAD.left : (coords[index - 1][0] + cx) / 2
    const right = index === coords.length - 1 ? WIDTH - PAD.right : (cx + coords[index + 1][0]) / 2
    return [left, Math.max(right - left, 8)] as const
  })

  return (
    <figure className="line-chart">
      <figcaption>
        <span>{title}</span>
        <strong>{format(active?.value ?? latest.value)}</strong>
        <small className="muted">{dateTimeFormat.format((active ?? latest).at)}</small>
      </figcaption>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${title} over time`}>
        <line className="axis" x1={PAD.left} x2={WIDTH - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH} />
        <text className="tick" x={PAD.left - 6} y={y(v1) + 4} textAnchor="end">
          {format(Math.round(v1 * 10) / 10)}
        </text>
        <text className="tick" x={PAD.left - 6} y={y(v0)} textAnchor="end">
          {format(Math.round(v0 * 10) / 10)}
        </text>
        <text className="tick" x={PAD.left} y={HEIGHT - 6} textAnchor="start">
          {dateFormat.format(new Date(t0))}
        </text>
        {t1 !== t0 && (
          <text className="tick" x={WIDTH - PAD.right} y={HEIGHT - 6} textAnchor="end">
            {dateFormat.format(new Date(t1))}
          </text>
        )}

        {activeXY && <line className="crosshair" x1={activeXY[0]} x2={activeXY[0]} y1={PAD.top} y2={PAD.top + plotH} />}
        {coords.length > 1 && <polyline className="series" points={line} />}
        {coords.map(([cx, cy], index) => (
          <circle
            key={points[index].at.getTime()}
            className={index === hover ? 'marker active' : 'marker'}
            cx={cx}
            cy={cy}
            r={4}
          />
        ))}
        {bands.map(([left, width], index) => (
          <rect
            key={`hit-${points[index].at.getTime()}`}
            className="hit"
            x={left}
            y={0}
            width={width}
            height={HEIGHT}
            onMouseEnter={() => setHover(index)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>
    </figure>
  )
}
