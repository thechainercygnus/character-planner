import { slotLabel, type Recommendations } from '../api'
import { levelRange, signed } from '../format'
import { PoolItemName } from './PoolItems'

/** Dungeons ranked by the upgrades they hold for you right now (ADR 0007). */
export function Dungeons({ data }: { data: Recommendations }) {
  return (
    <section>
      <h2>
        Dungeons worth running <span className="muted">by total score gain of upgrades you can wear now</span>
      </h2>
      {data.dungeons.length === 0 ? (
        <p className="muted">No dungeon in reach holds an upgrade you can wear yet.</p>
      ) : (
        <div className="dungeon-cards">
          {data.dungeons.map((dungeon, index) => (
            <article key={dungeon.dungeon_id} className="dungeon-card">
              <header>
                <h3>
                  <span className="muted">{index + 1}.</span> {dungeon.dungeon}
                  {(dungeon.min_level !== null || dungeon.max_level !== null) && (
                    <span className="muted"> · levels {levelRange(dungeon.min_level, dungeon.max_level)}</span>
                  )}
                </h3>
                <span className="badge verdict-upgrade">{signed(dungeon.total_gain, 1)}</span>
              </header>
              <ul>
                {dungeon.upgrades.map((upgrade) => (
                  <li key={upgrade.item.item_id}>
                    <span className="muted slot-label">{slotLabel(upgrade.slot)}</span>
                    <PoolItemName item={upgrade.item} />
                    <span className="muted upgrade-source">
                      {upgrade.source.kind === 'quest'
                        ? `Quest: ${upgrade.source.detail ?? '?'}`
                        : (upgrade.source.detail ?? 'drop')}
                    </span>
                    <span className="gain">{signed(upgrade.score_gain, 1)}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
