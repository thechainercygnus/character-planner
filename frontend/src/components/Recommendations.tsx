import type { ReactNode } from 'react'
import {
  slotLabel,
  type Candidate,
  type DungeonValue,
  type PoolSource,
  type Recommendations as RecommendationsData,
} from '../api'
import { Icon, ItemName } from './GearTable'

function signed(value: number, digits = 0): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`
}

function levels(min: number | null, max: number | null): string {
  if (min === null && max === null) return ''
  if (min === max || max === null) return ` (${min})`
  if (min === null) return ` (${max})`
  return ` (${min}–${max})`
}

function sourceText(source: PoolSource): string {
  if (source.kind === 'quest') {
    return `Quest: ${source.detail ?? '?'} (${source.dungeon})${source.choice ? ', choice' : ''}`
  }
  return source.detail ? `${source.dungeon} – ${source.detail}` : source.dungeon
}

function CandidateItem({ candidate }: { candidate: Candidate }) {
  const { item } = candidate
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = [
    item.item_level !== null ? `ilvl ${item.item_level}` : null,
    item.weapon_type ?? item.armor_type,
    item.armor ? `${item.armor} armor` : null,
    item.dps ? `${item.dps} dps` : null,
    ...Object.entries(item.stats).map(([name, value]) => `+${value} ${name}`),
  ].filter(Boolean)

  return (
    <div className="item-cell">
      <Icon url={item.icon_url} />
      <span className={`item quality-${quality}`}>
        {item.wowhead ? (
          <a className="item-link" href={item.wowhead} target="_blank" rel="noreferrer">
            {item.name}
          </a>
        ) : (
          item.name
        )}
        {candidate.is_target && <span className="tag">your target</span>}
        {!candidate.usable_now && <span className="tag warn">level {item.effective_level}</span>}
        {details.length > 0 && <small>{details.join(' · ')}</small>}
        <small className="source-line">{item.sources.map(sourceText).join('; ')}</small>
      </span>
    </div>
  )
}

function Gain({ candidate }: { candidate: Candidate }) {
  const parts = [
    candidate.armor_delta ? `${signed(candidate.armor_delta)} armor` : null,
    ...Object.entries(candidate.stat_deltas).map(([name, change]) => `${signed(change)} ${name}`),
  ].filter(Boolean)
  return (
    <div>
      <span className="badge verdict-upgrade" title="Weighted stat score vs what you wear">
        {signed(candidate.score_gain, 1)} score
      </span>
      {candidate.item_level_delta !== null && candidate.item_level_delta !== 0 && (
        <small className="muted">{signed(candidate.item_level_delta)} item level</small>
      )}
      {parts.length > 0 && <small className="gains">{parts.join(' · ')}</small>}
    </div>
  )
}

function DungeonList({ dungeons }: { dungeons: DungeonValue[] }) {
  if (dungeons.length === 0) return null
  return (
    <>
      <h3>Dungeons worth running</h3>
      <ol className="dungeon-values">
        {dungeons.slice(0, 5).map((dungeon) => (
          <li key={dungeon.dungeon_id}>
            <strong>
              {dungeon.dungeon}
              {levels(dungeon.min_level, dungeon.max_level)}
            </strong>{' '}
            <span className="badge verdict-upgrade">{signed(dungeon.total_gain, 1)} score</span>
            <small className="muted">{dungeon.upgrades.join(' · ')}</small>
          </li>
        ))}
      </ol>
    </>
  )
}

/** Best upgrades in reach for each slot, proposed from the item pool (ADR 0007). */
export function Recommendations({ data, actions }: { data: RecommendationsData; actions?: ReactNode }) {
  const empty = data.considered === 0 && data.unscored === 0
  const withUpgrades = data.rows.filter((row) => row.candidates.length > 0)

  return (
    <section>
      <div className="section-heading">
        <h2>
          Recommended upgrades{' '}
          {data.window && (
            <span className="muted">
              dungeons for levels {data.window[0]}–{data.window[1]}
            </span>
          )}
        </h2>
        {actions}
      </div>

      {empty ? (
        <p className="muted">
          No item pool yet. Click <strong>Refresh item pool</strong> above (the first run takes a few minutes).
        </p>
      ) : (
        <>
          <p className="muted">
            {withUpgrades.length} of {data.rows.length} slots have an upgrade in reach, from {data.considered} usable
            items
            {data.unscored > 0 && ` (${data.unscored} more without stats yet)`}.
          </p>
          <DungeonList dungeons={data.dungeons} />
          <table className="gear">
            <thead>
              <tr>
                <th>Slot</th>
                <th>Equipped</th>
                <th>Best upgrade</th>
                <th>Gain</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => {
                const [best, ...others] = row.candidates
                return (
                  <tr key={row.slot} className={best ? undefined : 'row-reached'}>
                    <td>{slotLabel(row.slot)}</td>
                    <td>
                      {row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}
                    </td>
                    <td>
                      {best ? (
                        <>
                          <CandidateItem candidate={best} />
                          {others.length > 0 && (
                            <details className="more-candidates">
                              <summary>
                                {others.length} more option{others.length === 1 ? '' : 's'}
                              </summary>
                              {others.map((candidate) => (
                                <div key={candidate.item.item_id} className="other-candidate">
                                  <CandidateItem candidate={candidate} />
                                  <span className="muted">{signed(candidate.score_gain, 1)}</span>
                                </div>
                              ))}
                            </details>
                          )}
                        </>
                      ) : (
                        <span className="muted">nothing better in reach</span>
                      )}
                    </td>
                    <td>{best && <Gain candidate={best} />}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}

      {data.attributions.map((credit) => (
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
