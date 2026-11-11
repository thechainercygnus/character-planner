import type { Attribution, PoolItem, PoolSource } from '../api'
import { Icon } from './GearTable'

export function signed(value: number, digits = 0): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

export function levelRange(min: number | null, max: number | null): string {
  if (min === null && max === null) return ''
  if (min === max || max === null) return `${min}`
  if (min === null) return `${max}`
  return `${min}–${max}`
}

export function sourceText(source: PoolSource): string {
  if (source.kind === 'quest') {
    return `Quest: ${source.detail ?? '?'} (${source.dungeon})${source.choice ? ', choice' : ''}`
  }
  return source.detail ? `${source.dungeon} – ${source.detail}` : source.dungeon
}

export function itemDetails(item: PoolItem): string {
  return [
    item.item_level !== null ? `ilvl ${item.item_level}` : null,
    item.weapon_type ?? item.armor_type,
    item.armor ? `${item.armor} armor` : null,
    item.dps ? `${item.dps} dps` : null,
    ...Object.entries(item.stats).map(([name, value]) => `+${value} ${name}`),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** Icon and quality-coloured name linking to Wowhead, with optional tags and lines below. */
export function PoolItemName({
  item,
  isTarget = false,
  usableNow = true,
  showDetails = false,
  showSources = false,
}: {
  item: PoolItem
  isTarget?: boolean
  usableNow?: boolean
  showDetails?: boolean
  showSources?: boolean
}) {
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = showDetails ? itemDetails(item) : ''
  return (
    <div className="item-cell">
      <Icon url={item.icon_url} />
      <span className={`item quality-${quality}`}>
        {item.wowhead ? (
          <a
            className="item-link"
            href={item.wowhead}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => event.stopPropagation()}
          >
            {item.name}
          </a>
        ) : (
          item.name
        )}
        {isTarget && <span className="tag">your target</span>}
        {!usableNow && <span className="tag warn">level {item.effective_level}</span>}
        {details && <small>{details}</small>}
        {showSources && <small className="source-line">{item.sources.map(sourceText).join('; ')}</small>}
      </span>
    </div>
  )
}

export function Attributions({ credits }: { credits: Attribution[] }) {
  return (
    <>
      {credits.map((credit) => (
        <p key={credit.url} className="attribution muted">
          {credit.text}{' '}
          <a href={credit.url} target="_blank" rel="noreferrer">
            {credit.name}
          </a>
        </p>
      ))}
    </>
  )
}
