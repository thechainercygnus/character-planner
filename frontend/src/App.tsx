import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { CharacterHeader } from './components/CharacterPanels'
import { ClassQuests } from './components/ClassQuests'
import { CharacterSnapshot } from './components/CharacterSnapshot'
import { Dungeons } from './components/Dungeons'
import { Enchants } from './components/Enchants'
import { Footer } from './components/Footer'
import { GearTable } from './components/GearTable'
import { Landing } from './components/Landing'
import { ProfessionMilestones } from './components/ProfessionMilestones'
import { Progress } from './components/Progress'
import { Recommendations } from './components/Recommendations'
import { RulesDialog } from './components/RulesDialog'
import { StatusBar } from './components/StatusBar'
import { TalentPlanPanel } from './components/TalentPlan'
import { TabBar } from './components/Tabs'
import { TargetsEditor } from './components/TargetsEditor'
import { useHashIs, useHashTab, type Tab } from './useHashTab'
import { WeightsDialog } from './components/WeightsDialog'
import './App.css'

type TabId = 'upgrades' | 'dungeons' | 'plan' | 'talents' | 'progress' | 'character'

const TABS: readonly Tab<TabId>[] = [
  { id: 'upgrades', label: 'Upgrades' },
  { id: 'dungeons', label: 'Dungeons' },
  { id: 'plan', label: 'Plan' },
  { id: 'talents', label: 'Talents' },
  { id: 'progress', label: 'Progress' },
  { id: 'character', label: 'Character' },
]

export default function App() {
  const [tab, setTab] = useHashTab(TABS, 'upgrades')
  const guestView = useHashIs('guest')
  const character = useQuery({ queryKey: ['character'], queryFn: api.character })
  const gear = useQuery({ queryKey: ['gear'], queryFn: api.gear })
  const recommendations = useQuery({ queryKey: ['recommendations'], queryFn: api.recommendations })
  const talents = useQuery({ queryKey: ['talents'], queryFn: api.talents, enabled: tab === 'talents' })
  const progress = useQuery({ queryKey: ['progress'], queryFn: api.progress, enabled: tab === 'progress' })
  const professions = useQuery({
    queryKey: ['professions'],
    queryFn: api.professions,
    enabled: tab === 'progress',
  })
  // On the Plan tab, and for its tab count: essential class quests missed (#8).
  const classQuests = useQuery({ queryKey: ['class-quests'], queryFn: api.classQuests })
  const enchants = useQuery({ queryKey: ['enchants'], queryFn: api.enchants, enabled: tab === 'upgrades' })

  const missedClassQuests = classQuests.data?.rows.filter((row) => row.status === 'missed').length
  const upgradeSlots = recommendations.data?.rows.filter((row) => row.candidates.length > 0).length
  const recommendationsError = recommendations.isError && (
    <p className="error">Couldn't load recommendations: {recommendations.error.message}</p>
  )

  return (
    <main>
      <StatusBar />

      {character.isPending && <p className="muted">Loading character…</p>}
      {character.isError && <p className="error">Couldn't load character: {character.error.message}</p>}

      {character.data && (character.data.level === null || guestView) && (
        <Landing hasCharacter={character.data.level !== null} />
      )}

      {character.data && character.data.level !== null && !guestView && (
        <>
          <CharacterHeader character={character.data} />
          <TabBar
            tabs={TABS}
            active={tab}
            onSelect={setTab}
            counts={{
              upgrades: upgradeSlots,
              dungeons: recommendations.data?.dungeons.length,
              plan: missedClassQuests || undefined,
            }}
          />

          {tab === 'upgrades' && (
            <>
              {recommendationsError}
              {recommendations.data && (
                <Recommendations
                  data={recommendations.data}
                  actions={
                    <div className="heading-actions">
                      <RulesDialog />
                      <WeightsDialog />
                    </div>
                  }
                />
              )}
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

          {tab === 'plan' && (
            <>
              {gear.data && (
                <GearTable
                  plan={gear.data}
                  actions={
                    <div className="heading-actions">
                      <TargetsEditor customised={gear.data.targets_customised} />
                      <WeightsDialog />
                    </div>
                  }
                />
              )}
              {classQuests.isError && (
                <p className="error">Couldn't load class quests: {classQuests.error.message}</p>
              )}
              {classQuests.data && <ClassQuests data={classQuests.data} />}
            </>
          )}

          {tab === 'progress' && (
            <>
              {progress.isError && <p className="error">Couldn't load progress: {progress.error.message}</p>}
              {progress.data && <Progress data={progress.data} />}
              {professions.isError && (
                <p className="error">Couldn't load professions: {professions.error.message}</p>
              )}
              {professions.data && <ProfessionMilestones data={professions.data} />}
            </>
          )}

          {tab === 'talents' && (
            <>
              {talents.isError && <p className="error">Couldn't load the talent plan: {talents.error.message}</p>}
              {talents.data && <TalentPlanPanel view={talents.data} />}
            </>
          )}

          {tab === 'character' && <CharacterSnapshot character={character.data} />}
        </>
      )}
      <Footer />
    </main>
  )
}
