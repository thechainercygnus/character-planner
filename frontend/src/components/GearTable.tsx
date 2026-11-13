import type { ReactNode } from 'react'
import {
  slotLabel,
  type EquippedItem,
  type GearPlan,
  type GearRow,
  type SourceName,
  type TargetInfo,
  type UpcomingTarget,
  type Verdict,
} from '../api'

export function Icon({ url }: { url: string | null }) {
  return url ? <img className="icon" src={url} alt="" width={28} height={28} /> : <span className="icon" />
}

/** An equipped item; `compact` leaves out the detail line. */
export function ItemName({ item, compact = false }: { item: EquippedItem; compact?: boolean }) {
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = [
    item.item_level !== null ? `ilvl ${item.item_level}` : null,
    item.armor_type,
    item.armor ? `${item.armor} armor` : null,
    ...item.stats.map((stat) => `+${stat.value} ${stat.name}`),
  ].filter((part) => !compact && Boolean(part))
  const enchants = (item.enchantments ?? []).map((e) => e.text.replace(/^Enchanted: /, ''))

  return (
    <div className="item-cell">
      <Icon url={item.icon_url} />
      <span className={`item quality-${quality}`}>
        {item.name}
        {details.length > 0 && <small>{details.join(' · ')}</small>}
        {!compact && enchants.length > 0 && <small className="enchant">✦ {enchants.join(' · ')}</small>}
      </span>
    </div>
  )
}

const SOURCE_LABEL: Record<SourceName, string> = {
  blizzard: 'Blizzard',
  companion: 'Forever Companion',
  manual: 'manual',
}

function sourcesText(info: TargetInfo): string {
  return info.sources
    .map((source) =>
      source === 'companion' && info.verified ? `${SOURCE_LABEL[source]} (${info.verified} verified)` : SOURCE_LABEL[source],
    )
    .join(' + ')
}

function TargetName({ row }: { row: GearRow }) {
  const info = row.target_info
  const quality = (info?.quality ?? 'COMMON').toLowerCase()
  const details = [
    info && info.item_level !== null ? `ilvl ${info.item_level}` : null,
    info?.armor_type,
    info?.armor ? `${info.armor} armor` : null,
    ...(info?.stats ?? []).map((stat) => `+${stat.value} ${stat.name}`),
  ].filter(Boolean)

  return (
    <div className="item-cell">
      <Icon url={info?.icon_url ?? null} />
      <span className={info ? `item quality-${quality}` : 'item'}>
        {info?.wowhead ? (
          <a className="item-link" href={info.wowhead} target="_blank" rel="noreferrer">
            {row.target.item}
          </a>
        ) : (
          row.target.item
        )}
        {info ? (
          <>
            {details.length > 0 && <small>{details.join(' · ')}</small>}
            <small className="source-line">from {sourcesText(info)}</small>
            {info.conflicts.map((conflict) => (
              <small key={conflict} className="warn">
                Sources disagree on {conflict}
              </small>
            ))}
          </>
        ) : (
          <small>no item data yet</small>
        )}
      </span>
    </div>
  )
}

function Gains({ row }: { row: GearRow }) {
  const parts = [
    row.armor_delta ? `${row.armor_delta > 0 ? '+' : ''}${row.armor_delta} armor` : null,
    ...Object.entries(row.stat_deltas).map(([name, change]) => `${change > 0 ? '+' : ''}${change} ${name}`),
  ].filter(Boolean)
  return parts.length > 0 ? <small className="gains">{parts.join(' · ')}</small> : null
}

const VERDICT_TEXT: Record<Verdict, string> = {
  reached: '✓ equipped',
  upgrade: 'upgrade',
  sidegrade: 'sidegrade',
  downgrade: 'outgrown',
  unknown: 'unknown',
}

function signed(value: number, digits = 0): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

export function VerdictBadge({ row }: { row: GearRow }) {
  const level = row.item_level_delta
  let deltaText = ''
  if (row.verdict_basis === 'score' && row.score_delta !== null) {
    deltaText = ` (${signed(row.score_delta, 1)} score)`
  } else if (level !== null && level !== 0) {
    deltaText = ` (${signed(level)} ilvl)`
  }
  return (
    <div>
      <span
        className={`badge verdict-${row.verdict}`}
        title={row.verdict_basis === 'score' ? 'Weighted stat score vs what you wear' : 'Item level vs what you wear'}
      >
        {VERDICT_TEXT[row.verdict]}
        {deltaText}
      </span>
      {row.verdict_basis === 'score' && level !== null && level !== 0 && (
        <small className="muted">{signed(level)} item level</small>
      )}
      <Gains row={row} />
      {row.warning && <small className="warn">{row.warning}</small>}
    </div>
  )
}

/** Where a target comes from: its drops when known, else the hand-written source. */
function sourceOf(target: { target: { source: string }; target_info: TargetInfo | null }): string {
  const drops = target.target_info?.drops ?? []
  return drops.length > 0 ? drops.join('; ') : target.target.source
}

/** A slot's next targets above the character's level, nearest first. */
function Upcoming({ upcoming }: { upcoming: UpcomingTarget[] }) {
  if (upcoming.length === 0) return <span className="muted">—</span>
  return (
    <ul className="upcoming">
      {upcoming.map((next, index) => (
        <li key={`${next.target.item}-${index}`} title={sourceOf(next)}>
          {next.target_info?.wowhead ? (
            <a className="item-link" href={next.target_info.wowhead} target="_blank" rel="noreferrer">
              {next.target.item}
            </a>
          ) : (
            next.target.item
          )}
          {next.target.pinned && <span className="muted"> (pinned)</span>}
          <small className="muted">
            {next.level !== null ? `level ${next.level}` : 'level unknown'}
            {next.score_delta !== null && ` · ${signed(next.score_delta, 1)} score`}
            {' · '}
            {sourceOf(next)}
          </small>
        </li>
      ))}
    </ul>
  )
}

/**
 * Per slot, the target to go for now and the ones coming up (ADR 0015). `actions` renders
 * on the right of the section heading (e.g. the stat weights button).
 */
export function GearTable({ plan, actions }: { plan: GearPlan; actions?: ReactNode }) {
  const heading = (
    <div className="section-heading">
      <h2>
        Gear targets {plan.level !== null && <span className="muted">level {plan.level}</span>}
      </h2>
      {actions}
    </div>
  )
  if (plan.rows.length === 0 && plan.later.length === 0) {
    return (
      <section>
        {heading}
        <p className="muted">No gear targets yet. Add some with Edit targets.</p>
      </section>
    )
  }

  const upgrades = plan.rows.filter((row) => row.verdict === 'upgrade').length
  // Rows arrive sorted by score gain (server-side), biggest first.
  const unknown = plan.rows.filter((row) => row.verdict === 'unknown').length

  return (
    <section>
      {heading}
      <p className="muted">
        {upgrades} upgrade{upgrades === 1 ? '' : 's'} to chase now
        {unknown > 0 && `, ${unknown} without item data`}. Each slot shows the target for your level and the next
        ones, so you can prepare for them.
      </p>
      {plan.rows.length > 0 && (
        <table className="gear">
          <thead>
            <tr>
              <th>Slot</th>
              <th>Equipped</th>
              <th>Target now</th>
              <th>Verdict</th>
              <th>Source</th>
              <th>Coming up</th>
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
                <td className="muted">{sourceOf(row)}</td>
                <td>
                  <Upcoming upcoming={row.upcoming} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {plan.later.length > 0 && (
        <>
          <h3>Coming up in other slots</h3>
          <table className="gear">
            <thead>
              <tr>
                <th>Slot</th>
                <th>Equipped</th>
                <th>Next targets</th>
              </tr>
            </thead>
            <tbody>
              {plan.later.map((slot) => (
                <tr key={slot.slot}>
                  <td>{slotLabel(slot.slot)}</td>
                  <td>{slot.equipped ? <ItemName item={slot.equipped} /> : <span className="muted">empty</span>}</td>
                  <td>
                    <Upcoming upcoming={slot.upcoming} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {plan.attributions.map((credit) => (
        <p key={credit.url} className="attribution muted">
          {credit.text}{' '}
          <a href={credit.url} target="_blank" rel="noreferrer">
            {credit.name}
          </a>
        </p>
      ))}
    </section>
  )
}
