import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import {
  CharacterHeader,
  EquipmentPanel,
  ProfessionsPanel,
  StatsPanel,
} from './components/CharacterPanels'
import { Dungeons } from './components/Dungeons'
import { Enchants } from './components/Enchants'
import { GearTable } from './components/GearTable'
import { Progress } from './components/Progress'
import { Recommendations } from './components/Recommendations'
import { StatusBar } from './components/StatusBar'
import { TalentPlanPanel } from './components/TalentPlan'
import { TabBar } from './components/Tabs'
import { useHashTab, type Tab } from './useHashTab'
import { WeightsDialog } from './components/WeightsDialog'
import './App.css'

type TabId = 'upgrades' | 'dungeons' | 'plan' | 'progress' | 'character'

const TABS: readonly Tab<TabId>[] = [
  { id: 'upgrades', label: 'Upgrades' },
  { id: 'dungeons', label: 'Dungeons' },
  { id: 'plan', label: 'Plan' },
  { id: 'progress', label: 'Progress' },
  { id: 'character', label: 'Character' },
]

export default function App() {
  const [tab, setTab] = useHashTab(TABS, 'upgrades')
  const character = useQuery({ queryKey: ['character'], queryFn: api.character })
  const gear = useQuery({ queryKey: ['gear'], queryFn: api.gear })
  const recommendations = useQuery({ queryKey: ['recommendations'], queryFn: api.recommendations })
  const talents = useQuery({ queryKey: ['talents'], queryFn: api.talents, enabled: tab === 'character' })
  const progress = useQuery({ queryKey: ['progress'], queryFn: api.progress, enabled: tab === 'progress' })
  const enchants = useQuery({ queryKey: ['enchants'], queryFn: api.enchants, enabled: tab === 'upgrades' })

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
              {enchants.isError && <p className="error">Couldn't load enchants: {enchants.error.message}</p>}
              {enchants.data && <Enchants data={enchants.data} />}
            </>
          )}

          {tab === 'dungeons' && (
            <>
              {recommendationsError}
              {recommendations.data && <Dungeons data={recommendations.data} />}
            </>
          )}

          {tab === 'plan' && gear.data && <GearTable plan={gear.data} actions={<WeightsDialog />} />}

          {tab === 'progress' && (
            <>
              {progress.isError && <p className="error">Couldn't load progress: {progress.error.message}</p>}
              {progress.data && <Progress data={progress.data} />}
            </>
          )}

          {tab === 'character' && (
            <>
              {talents.isError && <p className="error">Couldn't load the talent plan: {talents.error.message}</p>}
              {talents.data && <TalentPlanPanel view={talents.data} />}
              <EquipmentPanel equipment={character.data.equipment} />
              <div className="panels">
                {character.data.stats && <StatsPanel stats={character.data.stats} />}
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
