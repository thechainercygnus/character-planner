import { slotLabel, type EquippedItem, type GearPlan, type GearRow, type Verdict } from '../api'

function Icon({ url }: { url: string | null }) {
  return url ? <img className="icon" src={url} alt="" width={28} height={28} /> : <span className="icon" />
}

function ItemName({ item }: { item: EquippedItem }) {
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = [
    item.item_level !== null ? `ilvl ${item.item_level}` : null,
    item.armor_type,
    item.armor ? `${item.armor} armor` : null,
    ...item.stats.map((stat) => `+${stat.value} ${stat.name}`),
  ].filter(Boolean)

  return (
    <div className="item-cell">
      <Icon url={item.icon_url} />
      <span className={`item quality-${quality}`}>
        {item.name}
        {details.length > 0 && <small>{details.join(' · ')}</small>}
      </span>
    </div>
  )
}

function TargetName({ row }: { row: GearRow }) {
  const info = row.target_info
  const quality = (info?.quality ?? 'COMMON').toLowerCase()
  const details = [
    info && info.item_level !== null ? `ilvl ${info.item_level}` : null,
    info?.armor_type,
    info?.armor ? `${info.armor} armor` : null,
    ...(info?.stats ?? []).map((stat) => `+${stat.value} ${stat.name}`),
    info?.source === 'manual' ? 'manual data' : null,
  ].filter(Boolean)

  return (
    <div className="item-cell">
      <Icon url={info?.icon_url ?? null} />
      <span className={info ? `item quality-${quality}` : 'item'}>
        {row.target.item}
        <small>{details.length > 0 ? details.join(' · ') : 'not in Battle.net item data'}</small>
      </span>
    </div>
  )
}

const VERDICT_TEXT: Record<Verdict, string> = {
  reached: '✓ equipped',
  upgrade: 'upgrade',
  sidegrade: 'sidegrade',
  downgrade: 'already better',
  unknown: 'unknown',
}

export function VerdictBadge({ row }: { row: GearRow }) {
  const delta = row.item_level_delta
  const deltaText = delta !== null && delta !== 0 ? ` (${delta > 0 ? '+' : ''}${delta} ilvl)` : ''
  return (
    <div>
      <span className={`badge verdict-${row.verdict}`}>
        {VERDICT_TEXT[row.verdict]}
        {deltaText}
      </span>
      {row.warning && <small className="warn">{row.warning}</small>}
    </div>
  )
}

export function GearTable({ plan }: { plan: GearPlan }) {
  if (plan.bracket_min_level === null) {
    return <p className="muted">No gear targets for this level yet.</p>
  }

  const upgrades = plan.rows.filter((row) => row.verdict === 'upgrade').length
  const unknown = plan.rows.filter((row) => row.verdict === 'unknown').length

  return (
    <section>
      <h2>
        Gear targets <span className="muted">level {plan.bracket_min_level}+</span>
      </h2>
      <p className="muted">
        {upgrades} upgrade{upgrades === 1 ? '' : 's'} to chase
        {unknown > 0 && `, ${unknown} without item data`}.
        {plan.next_bracket_level !== null &&
          ` Next bracket at level ${plan.next_bracket_level} (${plan.next_bracket_size} targets).`}
      </p>
      <table className="gear">
        <thead>
          <tr>
            <th>Slot</th>
            <th>Equipped</th>
            <th>Target</th>
            <th>Verdict</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {plan.rows.map((row) => (
            <tr key={row.slot} className={`row-${row.verdict}`}>
              <td>{slotLabel(row.slot)}</td>
              <td>{row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}</td>
              <td>
                <TargetName row={row} />
              </td>
              <td>
                <VerdictBadge row={row} />
              </td>
              <td className="muted">{row.target.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
