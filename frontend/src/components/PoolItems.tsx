import type { OwnedItem, PoolItem, PoolSource, QuestStep } from '../api'
import { itemDetails, questLevel, questWhere, sourceText } from '../format'
import { Icon } from './GearTable'
import { OwnedTag } from './OwnedTag'
import { QuestTag } from './QuestTag'
import { ItemLink } from './ItemLink'

/** Icon and quality-coloured name linking to Wowhead, with optional tags and lines below. */
export function PoolItemName({
  item,
  isTarget = false,
  usableNow = true,
  showDetails = false,
  showSources = false,
  owned = null,
}: {
  item: PoolItem
  isTarget?: boolean
  usableNow?: boolean
  showDetails?: boolean
  showSources?: boolean
  /** Already in the bags or bank (#186). */
  owned?: OwnedItem | null
}) {
  const quality = (item.quality ?? 'COMMON').toLowerCase()
  const details = showDetails ? itemDetails(item) : ''
  return (
    <div className="item-cell">
      <Icon url={item.icon_url} />
      <div className={`item quality-${quality}`}>
        <ItemLink href={item.wowhead}>{item.name}</ItemLink>
        {isTarget && <span className="tag">your target</span>}
        <OwnedTag owned={owned} />
        {!usableNow && <span className="tag warn">level {item.effective_level}</span>}
        {details && <small>{details}</small>}
        {showSources && <small className="source-line">{item.sources.map(sourceText).join('; ')}</small>}
        {showSources &&
          item.sources
            .filter((source) => source.kind === 'quest' && source.chain.length === 0 && source.quest)
            .filter((source) => source.quest?.progress || source.quest?.completed)
            .map((source) => (
              // A reward quest with no chain to show it in: its state from the game (#186).
              <small key={`${source.dungeon_id}:${source.detail}:state`} className="source-line">
                {source.quest!.name} <QuestTag progress={source.quest!.progress} completed={source.quest!.completed} />
              </small>
            ))}
        {showSources &&
          item.sources
            .filter((source) => source.kind === 'quest' && source.chain.length > 0)
            .map((source) => <QuestChain key={`${source.dungeon_id}:${source.detail}`} source={source} />)}
      </div>
    </div>
  )
}

function QuestName({ step }: { step: QuestStep }) {
  return step.wowhead ? (
    <a href={step.wowhead} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
      {step.name}
    </a>
  ) : (
    <>{step.name}</>
  )
}

/** One step of a chain: its quests (done side by side), with level, giver and place where known. */
function ChainStep({ quests }: { quests: QuestStep[] }) {
  return (
    <>
      {quests.map((step, i) => {
        const level = questLevel(step)
        const where = questWhere(step)
        return (
          <span key={step.quest_id ?? step.name}>
            {i > 0 && ' + '}
            <QuestName step={step} />
            <QuestTag progress={step.progress} completed={step.completed} />
            {level !== null && <span className="muted"> (level {level})</span>}
            {where && <span className="muted"> – {where}</span>}
          </span>
        )
      })}
    </>
  )
}

/**
 * The quests to do before a reward's quest (#7), earliest first, then the quest itself.
 * Forever Companion describes dungeon and elite quests; zone quests show their name only,
 * linked to Wowhead.
 */
function QuestChain({ source }: { source: PoolSource }) {
  const last: QuestStep = source.quest ?? {
    quest_id: null,
    name: source.detail ?? '?',
    level: null,
    min_level: source.quest_min_level,
    giver: null,
    location: null,
    zone: null,
    dungeon: source.dungeon,
    wowhead: null,
    known: false,
    progress: null,
    completed: false,
  }
  return (
    <ol className="quest-chain" aria-label={`Quest chain for ${last.name}`}>
      {source.chain.map((quests) => (
        <li key={quests.map((q) => q.quest_id ?? q.name).join('+')}>
          <ChainStep quests={quests} />
        </li>
      ))}
      <li className="quest-chain-reward">
        <ChainStep quests={[last]} />
      </li>
    </ol>
  )
}
