import { ResponsiveTable } from './ResponsiveTable'
import { slotLabel, type CharacterView, type EquippedItem, type Profession, type Stats } from '../api'
import { ago, parseTime } from '../gameData'
import { ItemName } from './GearTable'

export function CharacterHeader({ character }: { character: CharacterView }) {
  const fullName = [character.name, character.surname].filter(Boolean).join(' ')
  const who = [character.race, character.specialization?.name, character.character_class]
    .filter(Boolean)
    .join(' ')
  // The level planning uses: the game's when its data is newer than the last sync (ADR 0052).
  const source = character.level_source
  const level = source?.level ?? character.level
  const fromGame =
    source?.source === 'game'
      ? `From the game, ${source.at ? ago(parseTime(source.at)) : 'at an unknown time'}: newer than the last sync` +
        (character.level !== null && character.level !== source.level ? ` (Battle.net says ${character.level})` : '')
      : null

  return (
    <header className="character-header">
      <h1>{fullName || 'Unknown character'}</h1>
      <p>
        Level {level ?? '?'}
        {fromGame && (
          <span className="muted level-source" title={fromGame}>
            {' '}
            (from the game)
          </span>
        )}{' '}
        {who}
        {character.guild && <> · &lt;{character.guild}&gt;</>}
        {character.equipped_item_level !== null && (
          <span title={`Average of the ${character.gear_slots_filled} gear slots filled (of 17)`}>
            {' '}
            · item level {character.equipped_item_level.toFixed(1)}{' '}
            <span className="muted">({character.gear_slots_filled}/17 slots)</span>
          </span>
        )}
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

const HIDDEN_SLOTS = new Set(['SHIRT', 'TABARD', 'AMMO'])

export function EquipmentPanel({ equipment }: { equipment: EquippedItem[] }) {
  const gear = equipment.filter((item) => !HIDDEN_SLOTS.has(item.slot))
  return (
    <section>
      <h2>Equipped</h2>
      <ResponsiveTable caption="Equipped gear">
        <thead>
          <tr>
            <th scope="col">Slot</th>
            <th scope="col">Equipped item</th>
          </tr>
        </thead>
        <tbody>
          {gear.map((item) => (
            <tr key={item.slot}>
              <th scope="row">{slotLabel(item.slot)}</th>
              <td data-label="Equipped item">
                <ItemName item={item} />
              </td>
            </tr>
          ))}
        </tbody>
      </ResponsiveTable>
    </section>
  )
}
