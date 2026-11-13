import { useState, type ReactNode } from 'react'
import { slotLabel, type Candidate, type Recommendations as RecommendationsData, type SlotRecommendation } from '../api'
import { ItemName } from './GearTable'
import { signed } from '../format'
import { ChoiceButtons, DismissedItems } from './ItemChoices'
import { PoolItemName } from './PoolItems'

function GainBadge({ candidate }: { candidate: Candidate }) {
  return (
    <span
      className={`badge ${candidate.score_gain > 0 ? 'verdict-upgrade' : 'verdict-sidegrade'}`}
      title="Weighted stat score vs what you wear"
    >
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

function RowDetails({ row, best, guest }: { row: SlotRecommendation; best: Candidate; guest: boolean }) {
  const others = row.candidates.slice(1)
  return (
    <div className="upgrade-details">
      {!guest && (
        <div>
          <h4>Equipped</h4>
          {row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}
        </div>
      )}
      <div>
        <h4>{guest ? 'Best item' : 'Best upgrade'}</h4>
        <PoolItemName item={best.item} showDetails showSources />
        <Changes candidate={best} />
        {!guest && <ChoiceButtons candidate={best} slot={row.slot} />}
      </div>
      {others.length > 0 && (
        <div>
          <h4>Other options</h4>
          {others.map((candidate) => (
            <div key={candidate.item.item_id} className="other-candidate">
              <div>
                <PoolItemName
                  item={candidate.item}
                  isTarget={candidate.is_target}
                  usableNow={candidate.usable_now}
                  showDetails
                  showSources
                />
                {!guest && <ChoiceButtons candidate={candidate} slot={row.slot} />}
              </div>
              <GainBadge candidate={candidate} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function UpgradeRow({ row, best, guest }: { row: SlotRecommendation; best: Candidate; guest: boolean }) {
  const [open, setOpen] = useState(false)
  const more = row.candidates.length - 1
  const toggle = () => setOpen((value) => !value)

  return (
    <>
      <tr className={open ? 'upgrade-row open' : 'upgrade-row'} onClick={toggle}>
        <td>{slotLabel(row.slot)}</td>
        {!guest && (
          <td>{row.equipped ? <ItemName item={row.equipped} compact /> : <span className="muted">empty</span>}</td>
        )}
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
          <td colSpan={guest ? 4 : 5}>
            <RowDetails row={row} best={best} guest={guest} />
          </td>
        </tr>
      )}
    </>
  )
}

/**
 * Best upgrades in reach for each slot, proposed from the item pool (ADR 0007). `guest`
 * (ADR 0017) leaves out what's worn and the buttons that store choices: nothing is worn,
 * and a guest's choices aren't kept.
 */
export function Recommendations({
  data,
  actions,
  guest = false,
}: {
  data: RecommendationsData
  actions?: ReactNode
  guest?: boolean
}) {
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
          {guest ? 'Best items for your level' : 'Recommended upgrades'}{' '}
          {data.window && (
            <span className="muted">
              dungeons for levels {data.window[0]}–{data.window[1]}
            </span>
          )}
        </h2>
        {actions}
      </div>

      {empty ? (
        guest ? (
          <p className="muted">No item data for this level yet.</p>
        ) : (
          <p className="muted">
            No item pool yet. Choose <strong>Refresh item pool</strong> from the ⋯ menu above (the first run takes
            a few minutes).
          </p>
        )
      ) : (
        <>
          <p className="muted">
            {withUpgrades.length} of {data.rows.length} slots have {guest ? 'an item' : 'an upgrade'} in reach, from{' '}
            {data.considered} usable items
            {data.unscored > 0 && ` (${data.unscored} more without stats yet)`}.{' '}
            {guest
              ? 'Click a row for details and the other options.'
              : 'Click a row for details, to pin an item as your target or to stop suggesting it.'}
          </p>
          <table className="gear upgrades">
            <thead>
              <tr>
                <th>Slot</th>
                {!guest && <th>Equipped</th>}
                <th>{guest ? 'Best item' : 'Best upgrade'}</th>
                <th>Score</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {withUpgrades.map(({ row, best }) => (
                <UpgradeRow key={row.slot} row={row} best={best} guest={guest} />
              ))}
            </tbody>
          </table>
          {without.length > 0 && (
            <p className="muted no-upgrades">
              No upgrades in reach: {without.map((row) => slotLabel(row.slot)).join(', ')}
            </p>
          )}
          {!guest && <DismissedItems />}
        </>
      )}

    </section>
  )
}
