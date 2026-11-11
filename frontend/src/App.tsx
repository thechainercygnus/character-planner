import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import {
  CharacterHeader,
  EquipmentPanel,
  ProfessionsPanel,
  StatsPanel,
  TalentsPanel,
} from './components/CharacterPanels'
import { Dungeons } from './components/Dungeons'
import { GearTable } from './components/GearTable'
import { Recommendations } from './components/Recommendations'
import { StatusBar } from './components/StatusBar'
import { TabBar, useHashTab, type Tab } from './components/Tabs'
import { WeightsDialog } from './components/WeightsDialog'
import './App.css'

type TabId = 'upgrades' | 'dungeons' | 'plan' | 'character'

const TABS: readonly Tab<TabId>[] = [
  { id: 'upgrades', label: 'Upgrades' },
  { id: 'dungeons', label: 'Dungeons' },
  { id: 'plan', label: 'Plan' },
  { id: 'character', label: 'Character' },
]

export default function App() {
  const character = useQuery({ queryKey: ['character'], queryFn: api.character })
  const gear = useQuery({ queryKey: ['gear'], queryFn: api.gear })
  const recommendations = useQuery({ queryKey: ['recommendations'], queryFn: api.recommendations })
  const [tab, setTab] = useHashTab(TABS, 'upgrades')

  const upgradeSlots = recommendations.data?.rows.filter((row) => row.candidates.length > 0).length
  const recommendationsError = recommendations.isError && (
    <p className="error">Couldn't load recommendations: {recommendations.error.message}</p>
  )

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
          <TabBar
            tabs={TABS}
            active={tab}
            onSelect={setTab}
            counts={{ upgrades: upgradeSlots, dungeons: recommendations.data?.dungeons.length }}
          />

          {tab === 'upgrades' && (
            <>
              {recommendationsError}
              {recommendations.data && <Recommendations data={recommendations.data} actions={<WeightsDialog />} />}
            </>
          )}

          {tab === 'dungeons' && (
            <>
              {recommendationsError}
              {recommendations.data && <Dungeons data={recommendations.data} />}
            </>
          )}

          {tab === 'plan' && gear.data && <GearTable plan={gear.data} actions={<WeightsDialog />} />}

          {tab === 'character' && (
            <>
              <EquipmentPanel equipment={character.data.equipment} />
              <div className="panels">
                {character.data.stats && <StatsPanel stats={character.data.stats} />}
                <TalentsPanel character={character.data} />
                {character.data.professions.length > 0 && (
                  <ProfessionsPanel professions={character.data.professions} />
                )}
              </div>
            </>
          )}
        </>
      )}
    </main>
  )
}
