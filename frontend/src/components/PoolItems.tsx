import type { PoolItem } from '../api'
import { itemDetails, sourceText } from '../format'
import { Icon } from './GearTable'

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
