import { slotLabel, type EquippedItem, type GearPlan } from '../api'

function ItemName({ item }: { item: EquippedItem }) {
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = [
    item.armor ? `${item.armor} armor` : null,
    ...item.stats.map((stat) => `+${stat.value} ${stat.name}`),
  ].filter(Boolean)

  return (
    <span className={`item quality-${quality}`} title={details.join(', ')}>
      {item.name}
      {details.length > 0 && <small>{details.join(', ')}</small>}
    </span>
  )
}

export function GearTable({ plan }: { plan: GearPlan }) {
  if (plan.bracket_min_level === null) {
    return <p className="muted">No gear targets for this level yet.</p>
  }

  const remaining = plan.rows.filter((row) => !row.reached).length

  return (
    <section>
      <h2>
        Gear targets <span className="muted">level {plan.bracket_min_level}+</span>
      </h2>
      <p className="muted">
        {remaining === 0 ? 'Every target reached.' : `${remaining} of ${plan.rows.length} still to get.`}
        {plan.next_bracket_level !== null &&
          ` Next bracket at level ${plan.next_bracket_level} (${plan.next_bracket_size} targets).`}
      </p>
      <table className="gear">
        <thead>
          <tr>
            <th>Slot</th>
            <th>Equipped</th>
            <th>Target</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {plan.rows.map((row) => (
            <tr key={row.slot} className={row.reached ? 'reached' : undefined}>
              <td>{slotLabel(row.slot)}</td>
              <td>{row.equipped ? <ItemName item={row.equipped} /> : <span className="muted">empty</span>}</td>
              <td>
                {row.reached ? '✓ ' : ''}
                {row.target.item}
              </td>
              <td className="muted">{row.target.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
