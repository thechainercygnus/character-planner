import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { CharacterHeader, ProfessionsPanel, StatsPanel, TalentsPanel } from './components/CharacterPanels'
import { GearTable } from './components/GearTable'
import { StatusBar } from './components/StatusBar'
import './App.css'

export default function App() {
  const character = useQuery({ queryKey: ['character'], queryFn: api.character })
  const gear = useQuery({ queryKey: ['gear'], queryFn: api.gear })

  return (
    <main>
      <StatusBar />

      {character.isPending && <p className="muted">Loading character…</p>}
      {character.isError && <p className="error">Couldn't load character: {character.error.message}</p>}

      {character.data && character.data.level === null && (
        <p className="muted">No character data yet. Log in with Battle.net, then sync.</p>
      )}

      {character.data && character.data.level !== null && (
        <>
          <CharacterHeader character={character.data} />
          {gear.data && <GearTable plan={gear.data} />}
          <div className="panels">
            {character.data.stats && <StatsPanel stats={character.data.stats} />}
            <TalentsPanel character={character.data} />
            {character.data.professions.length > 0 && (
              <ProfessionsPanel professions={character.data.professions} />
            )}
          </div>
        </>
      )}
    </main>
  )
}
