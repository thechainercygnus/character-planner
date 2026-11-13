import { slotLabel, type EnchantAdvice, type EnchantPick, type SlotEnchants } from '../api'
import { signed } from '../format'
import { EffectEditor, OptionCorrections, PerSlotControl } from './EnchantCorrections'

/** "Enchant Bracer - Minor Deflect" -> "Minor Deflect": the slot is already in the row. */
function shortName(name: string): string {
  return name.replace(/^Enchant [^-]+ - /, '')
}

function effectText(effects: Record<string, number>): string {
  return Object.entries(effects)
    .map(([stat, value]) => `${signed(value)} ${stat}`)
    .join(', ')
}

function Pick({ pick }: { pick: EnchantPick }) {
  const { option } = pick
  return (
    <div className="enchant-pick">
      <span title={option.text ?? undefined}>{shortName(option.name)}</span>{' '}
      <small className="muted">
        {effectText(option.effects)} · {option.profession}
      </small>{' '}
      {pick.can_make && <span className="tag">you can make this</span>}
      {!pick.usable_now && <span className="tag warn">level {option.estimated_level}</span>}{' '}
      <span className="badge verdict-upgrade" title="Weighted stat score vs the enchant on now">
        {signed(pick.score_gain, 1)}
      </span>
      <OptionCorrections option={option} />
    </div>
  )
}

function Row({ row }: { row: SlotEnchants }) {
  return (
    <tr>
      <td>{slotLabel(row.slot)}</td>
      <td>
        {row.item ?? <span className="muted">empty</span>}
        {row.current && (
          <small className="enchant">
            {' '}
            ✦ {row.current.text.replace(/^Enchanted: /, '')}
            {row.current_is_weaker && <span className="tag warn">weaker than the best</span>}
          </small>
        )}
      </td>
      <td>
        {row.picks.length > 0 ? (
          row.picks.map((pick) => <Pick key={pick.option.recipe_id} pick={pick} />)
        ) : (
          <span className="muted">{row.item ? 'nothing better in reach' : 'nothing to enchant'}</span>
        )}
      </td>
    </tr>
  )
}

/** Enchants worth looking for, per slot, against what's on now (ADR 0010). */
export function Enchants({ data }: { data: EnchantAdvice }) {
  const withPicks = data.rows.filter((row) => row.picks.length > 0).length
  const left = [
    data.unscored > 0 && `${data.unscored} in reach have no stat to weigh (procs, or scopes and kits without known effects)`,
    data.unknown_level > 0 && `${data.unknown_level} have no level estimate`,
  ].filter(Boolean)

  return (
    <section>
      <div className="section-heading">
        <h2>
          Enchants <span className="muted">what to look for</span>
        </h2>
        {data.recipes > 0 && <PerSlotControl perSlot={data.per_slot} corrected={data.per_slot_corrected} />}
      </div>
      {data.recipes === 0 ? (
        <p className="muted">
          No enchant data yet. Choose <strong>Refresh enchant data</strong> from the ⋯ menu above.
        </p>
      ) : (
        <>
          <p className="muted">
            {withPicks} of {data.rows.length} slots have a better enchant in reach, scored with your stat weights.
            Levels are estimated from the materials.
          </p>
          <table className="gear enchants">
            <thead>
              <tr>
                <th>Slot</th>
                <th>Equipped</th>
                <th>Look for</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <Row key={row.slot} row={row} />
              ))}
            </tbody>
          </table>
          {left.length > 0 && <p className="muted no-upgrades">Not ranked: {left.join('; ')}.</p>}
          {data.missing_effects.length > 0 && (
            <details className="enchant-corrections missing-effects">
              <summary>
                {data.missing_effects.length} crafted enchant{data.missing_effects.length === 1 ? '' : 's'} in reach
                without a known effect: add {data.missing_effects.length === 1 ? 'it' : 'them'} from the game to rank
                them
              </summary>
              <ul>
                {data.missing_effects.map((missing) => (
                  <li key={missing.item_id}>
                    <strong>{missing.recipe}</strong>{' '}
                    <small className="muted">{missing.slots.map(slotLabel).join(', ')}</small>
                    <EffectEditor itemId={missing.item_id} effects={{}} corrected={false} label={missing.recipe} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  )
}
