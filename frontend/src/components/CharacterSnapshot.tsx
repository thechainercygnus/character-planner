import type { CharacterView, Specialization, Talent } from '../api'
import { EquipmentPanel, ProfessionsPanel, StatsPanel } from './CharacterPanels'

/** Talents as spent at the last sync, read-only: points per tree, then each tree's talents. */
export function TalentsSpentPanel({ specialization }: { specialization: Specialization }) {
  const trees = specialization.trees?.length
    ? specialization.trees
    : [{ name: specialization.name, spent_points: specialization.spent_points }]
  const byTree = new Map<string, Talent[]>()
  for (const talent of specialization.talents) {
    const tree = talent.tree ?? specialization.name
    byTree.set(tree, [...(byTree.get(tree) ?? []), talent])
  }
  return (
    <section aria-label="Talents">
      <h2>
        Talents{' '}
        <span className="muted">
          {trees.map((tree) => `${tree.name} ${tree.spent_points ?? '?'}`).join(' · ')}
        </span>
      </h2>
      <div className="talents-spent">
        {trees.map((tree) => (
          <div key={tree.name}>
            <h3>{tree.name}</h3>
            <ul>
              {(byTree.get(tree.name) ?? []).map((talent) => (
                <li key={talent.name} title={talent.description ?? undefined}>
                  {talent.name} <span className="muted">{talent.rank ?? '?'}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}

/**
 * The character as it was at the last sync, armory-style, with nothing to edit (#41):
 * talents as spent, equipment with enchants, stats and professions. It takes only the
 * character view (no plan, no settings), so #42's public page can show it as it is.
 */
export function CharacterSnapshot({ character }: { character: CharacterView }) {
  return (
    <>
      {character.specialization && <TalentsSpentPanel specialization={character.specialization} />}
      <EquipmentPanel equipment={character.equipment} />
      <div className="panels">
        {character.stats && <StatsPanel stats={character.stats} />}
        {character.professions.length > 0 && <ProfessionsPanel professions={character.professions} />}
      </div>
      {character.captured_at && (
        <p className="muted snapshot-time">
          From Blizzard's Battle.net API, as of the last sync, {new Date(character.captured_at).toLocaleString()}.
        </p>
      )}
    </>
  )
}
