import type { CharacterView, Profession, Stats } from '../api'

export function CharacterHeader({ character }: { character: CharacterView }) {
  const fullName = [character.name, character.surname].filter(Boolean).join(' ')
  const who = [character.race, character.specialization?.name, character.character_class]
    .filter(Boolean)
    .join(' ')

  return (
    <header className="character-header">
      <h1>{fullName || 'Unknown character'}</h1>
      <p>
        Level {character.level ?? '?'} {who}
        {character.guild && <> · &lt;{character.guild}&gt;</>}
        {character.equipped_item_level !== null && <> · item level {character.equipped_item_level}</>}
      </p>
    </header>
  )
}

const STAT_ROWS: [label: string, key: keyof Stats, percent?: boolean][] = [
  ['Health', 'health'],
  ['Armor', 'armor'],
  ['Defense', 'defense'],
  ['Stamina', 'stamina'],
  ['Strength', 'strength'],
  ['Agility', 'agility'],
  ['Attack power', 'attack_power'],
  ['Dodge', 'dodge', true],
  ['Parry', 'parry', true],
  ['Block', 'block', true],
  ['Crit', 'crit', true],
]

export function StatsPanel({ stats }: { stats: Stats }) {
  return (
    <section>
      <h2>Stats</h2>
      <dl className="stats">
        {STAT_ROWS.map(([label, key, percent]) => {
          const value = stats[key]
          return (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{value === null ? '?' : percent ? `${value.toFixed(1)}%` : value}</dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}

function ProfessionBar({ profession }: { profession: Profession }) {
  const { skill, max_skill: max } = profession
  return (
    <li>
      <span>{profession.name}</span>
      {skill !== null && max ? (
        <>
          <progress value={skill} max={max} />
          <span className="muted">
            {skill}/{max}
          </span>
        </>
      ) : (
        <span className="muted">?</span>
      )}
    </li>
  )
}

export function ProfessionsPanel({ professions }: { professions: Profession[] }) {
  return (
    <section>
      <h2>Professions</h2>
      <ul className="professions">
        {professions.map((profession) => (
          <ProfessionBar key={profession.name} profession={profession} />
        ))}
      </ul>
    </section>
  )
}

export function TalentsPanel({ character }: { character: CharacterView }) {
  const spec = character.specialization
  if (!spec) return null
  return (
    <section>
      <h2>
        Talents <span className="muted">{spec.spent_points ?? '?'} points in {spec.name}</span>
      </h2>
      <ul className="talents">
        {spec.talents.map((talent) => (
          <li key={talent.name} title={talent.description ?? undefined}>
            {talent.name} <span className="muted">rank {talent.rank ?? '?'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
