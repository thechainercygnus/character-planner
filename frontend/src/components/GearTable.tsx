import { useId, type ReactNode } from 'react'
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
import { OwnedTag } from './OwnedTag'
import { QuestTag } from './QuestTag'
import { ItemLink } from './ItemLink'

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
        <ItemLink href={item.wowhead}>{item.name}</ItemLink>
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
        <ItemLink href={info?.wowhead ?? row.target.wowhead}>{row.target.item}</ItemLink>
        <OwnedTag owned={row.owned} />
        <QuestTag progress={row.quest} named />
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
      {upcoming.map((next) => (
        <li key={`${next.target.item}@${next.level ?? '?'}`} title={sourceOf(next)}>
          <ItemLink href={next.target_info?.wowhead ?? next.target.wowhead}>{next.target.item}</ItemLink>
          {next.target.pinned && <span className="muted"> (pinned)</span>}
          <OwnedTag owned={next.owned} />
          <QuestTag progress={next.quest} named />
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
  const captionId = useId()
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
        <div className="gear-scroll" role="region" aria-labelledby={captionId} tabIndex={0}>
          <table className="gear">
            <caption id={captionId} className="visually-hidden">Current gear targets</caption>
            <thead>
              <tr>
                <th scope="col">Slot</th>
                <th scope="col">Equipped</th>
                <th scope="col">Target now</th>
                <th scope="col">Verdict</th>
                <th scope="col">Source</th>
                <th scope="col">Coming up</th>
              </tr>
            </thead>
            <tbody>
              {plan.rows.map((row) => (
                <tr key={row.slot} className={`row-${row.verdict}`}>
                  <th scope="row">{slotLabel(row.slot)}</th>
                  <td data-label="Equipped">
                    {row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}
                  </td>
                  <td data-label="Target now">
                    <TargetName row={row} />
                  </td>
                  <td data-label="Verdict">
                    <VerdictBadge row={row} />
                  </td>
                  <td className="muted" data-label="Source">{sourceOf(row)}</td>
                  <td data-label="Coming up">
                    <Upcoming upcoming={row.upcoming} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {plan.later.length > 0 && (
        <>
          <h3>Coming up in other slots</h3>
          <div className="gear-scroll" role="region" aria-labelledby={`${captionId}-later`} tabIndex={0}>
            <table className="gear">
              <caption id={`${captionId}-later`} className="visually-hidden">Upcoming gear targets</caption>
              <thead>
                <tr>
                  <th scope="col">Slot</th>
                  <th scope="col">Equipped</th>
                  <th scope="col">Next targets</th>
                </tr>
              </thead>
              <tbody>
                {plan.later.map((slot) => (
                  <tr key={slot.slot}>
                    <th scope="row">{slotLabel(slot.slot)}</th>
                    <td data-label="Equipped">
                      {slot.equipped ? <ItemName item={slot.equipped} /> : <span className="muted">empty</span>}
                    </td>
                    <td data-label="Next targets">
                      <Upcoming upcoming={slot.upcoming} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
