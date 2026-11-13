import type { ProfessionRow, ProfessionsView } from '../api'

function NextRankLine({ row, level }: { row: ProfessionRow; level: number | null }) {
  const next = row.next_rank
  if (!next) return <small className="muted">{row.rank ? 'Last rank reached.' : 'Rank unknown.'}</small>
  const needs = [
    next.skill_ready ? null : `${next.train_at_skill} skill (${next.train_at_skill - (row.skill ?? 0)} to go)`,
    next.level_ready ? null : `level ${next.train_at_level}${level !== null ? ` (${next.train_at_level - level} to go)` : ''}`,
  ].filter(Boolean)
  return (
    <small className={needs.length === 0 ? 'ok' : 'muted'}>
      {needs.length === 0
        ? `${next.name} (cap ${next.max_skill}) can be trained now.`
        : `${next.name} (cap ${next.max_skill}) at ${needs.join(' and ')}.`}
      {row.note && ` ${row.note}`}
    </small>
  )
}

/**
 * Each synced profession against its trainer ranks (#10): skill toward the cap, the next
 * rank and what it needs, and the gear its known recipes make. Ranks are Classic's, from
 * data/curated/professions.yaml.
 */
export function ProfessionMilestones({ data }: { data: ProfessionsView }) {
  if (data.professions.length === 0) return null
  return (
    <section>
      <h2>Professions</h2>
      <ul className="profession-milestones">
        {data.professions.map((row) => (
          <li key={row.name} aria-label={row.name}>
            <div className="profession-head">
              <strong>{row.name}</strong>
              {row.rank && <span className="muted"> {row.rank}</span>}
              <span className="profession-skill">
                {row.skill ?? '?'} / {row.max_skill ?? '?'}
              </span>
            </div>
            <progress value={row.skill ?? 0} max={row.max_skill ?? 1} aria-label={`${row.name} skill`} />
            <NextRankLine row={row} level={data.level} />
            {row.crafted_gear.length > 0 && (
              <small className="muted">Crafts gear: {row.crafted_gear.join(', ')}</small>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
