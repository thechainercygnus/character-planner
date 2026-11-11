import { useState, type ReactNode } from 'react'
import { slotLabel, type Candidate, type Recommendations as RecommendationsData, type SlotRecommendation } from '../api'
import { ItemName } from './GearTable'
import { signed } from '../format'
import { Attributions, PoolItemName } from './PoolItems'

function GainBadge({ candidate }: { candidate: Candidate }) {
  return (
    <span className="badge verdict-upgrade" title="Weighted stat score vs what you wear">
      {signed(candidate.score_gain, 1)}
    </span>
  )
}

function Changes({ candidate }: { candidate: Candidate }) {
  const parts = [
    candidate.item_level_delta ? `${signed(candidate.item_level_delta)} item level` : null,
    candidate.armor_delta ? `${signed(candidate.armor_delta)} armor` : null,
    ...Object.entries(candidate.stat_deltas).map(([name, change]) => `${signed(change)} ${name}`),
  ].filter(Boolean)
  return parts.length > 0 ? <small className="gains">{parts.join(' · ')}</small> : null
}

function RowDetails({ row, best }: { row: SlotRecommendation; best: Candidate }) {
  const others = row.candidates.slice(1)
  return (
    <div className="upgrade-details">
      <div>
        <h4>Equipped</h4>
        {row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}
      </div>
      <div>
        <h4>Best upgrade</h4>
        <PoolItemName item={best.item} showDetails showSources />
        <Changes candidate={best} />
      </div>
      {others.length > 0 && (
        <div>
          <h4>Other options</h4>
          {others.map((candidate) => (
            <div key={candidate.item.item_id} className="other-candidate">
              <PoolItemName
                item={candidate.item}
                isTarget={candidate.is_target}
                usableNow={candidate.usable_now}
                showDetails
                showSources
              />
              <GainBadge candidate={candidate} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function UpgradeRow({ row, best }: { row: SlotRecommendation; best: Candidate }) {
  const [open, setOpen] = useState(false)
  const more = row.candidates.length - 1
  const toggle = () => setOpen((value) => !value)

  return (
    <>
      <tr className={open ? 'upgrade-row open' : 'upgrade-row'} onClick={toggle}>
        <td>{slotLabel(row.slot)}</td>
        <td>{row.equipped ? <ItemName item={row.equipped} compact /> : <span className="muted">empty</span>}</td>
        <td>
          <PoolItemName item={best.item} isTarget={best.is_target} usableNow={best.usable_now} />
        </td>
        <td>
          <GainBadge candidate={best} />
        </td>
        <td className="expand-cell">
          <button
            type="button"
            className="expand"
            aria-expanded={open}
            aria-label={`${open ? 'Hide' : 'Show'} details for ${slotLabel(row.slot)}`}
            onClick={(event) => {
              event.stopPropagation()
              toggle()
            }}
          >
            {open ? '▾' : '▸'}
            {more > 0 && <span className="muted"> +{more}</span>}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="upgrade-details-row">
          <td colSpan={5}>
            <RowDetails row={row} best={best} />
          </td>
        </tr>
      )}
    </>
  )
}

/** Best upgrades in reach for each slot, proposed from the item pool (ADR 0007). */
export function Recommendations({ data, actions }: { data: RecommendationsData; actions?: ReactNode }) {
  const empty = data.considered === 0 && data.unscored === 0
  const without = data.rows.filter((row) => row.candidates.length === 0)
  const withUpgrades = data.rows.flatMap((row) => {
    const best = row.candidates.at(0)
    return best ? [{ row, best }] : []
  })

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
          No item pool yet. Choose <strong>Refresh item pool</strong> from the ⋯ menu above (the first run takes a
          few minutes).
        </p>
      ) : (
        <>
          <p className="muted">
            {withUpgrades.length} of {data.rows.length} slots have an upgrade in reach, from {data.considered} usable
            items
            {data.unscored > 0 && ` (${data.unscored} more without stats yet)`}. Click a row for details.
          </p>
          <table className="gear upgrades">
            <thead>
              <tr>
                <th>Slot</th>
                <th>Equipped</th>
                <th>Best upgrade</th>
                <th>Score</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {withUpgrades.map(({ row, best }) => (
                <UpgradeRow key={row.slot} row={row} best={best} />
              ))}
            </tbody>
          </table>
          {without.length > 0 && (
            <p className="muted no-upgrades">
              No upgrades in reach: {without.map((row) => slotLabel(row.slot)).join(', ')}
            </p>
          )}
        </>
      )}

      <Attributions credits={data.attributions} />
    </section>
  )
}
