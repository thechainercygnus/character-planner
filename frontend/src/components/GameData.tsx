import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import {
  api,
  type GameDataView,
  type PlanningLevel,
  type GameItem,
  type GameItemInfo,
  type GameItems,
  type GameQuest,
} from '../api'
import { ago, parseTime, stacked } from '../gameData'
import { Icon } from './GearTable'
import { ItemLink } from './ItemLink'

/** Enum.ItemQuality's order (addon/SCHEMA.md), for items no catalog knows yet. */
const QUALITY = ['poor', 'common', 'uncommon', 'rare', 'epic', 'legendary', 'artifact', 'heirloom']

/** "From the game, 2 days ago": every section says how old it is (#185). */
function FromTheGame({ at }: { at: string | null }) {
  if (!at) return null
  const when = parseTime(at)
  return (
    <span className="muted" title={when.toLocaleString()}>
      From the game, {ago(when)}
    </span>
  )
}

const count = (n: number, what: string) => `${n} ${what}${n === 1 ? '' : 's'}`

const WHERE = String.raw`_forever_\WTF\Account\<ACCOUNT>\91\<Character>\SavedVariables\CharacterPlannerExport.lua`

/** Upload the addon's SavedVariables file for the selected character (#185). */
export function ImportGameDataDialog({ label = 'Import game data' }: { label?: string }) {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const view = useQuery({ queryKey: ['game-data'], queryFn: api.gameData })
  const onSaved = (saved: GameDataView) => {
    queryClient.setQueryData(['game-data'], saved)
    // Item names and icons are looked up in the background: watch the status for it.
    void queryClient.invalidateQueries({ queryKey: ['status'] })
  }
  const upload = useMutation({ mutationFn: api.importGameData, onSuccess: onSaved })
  const remove = useMutation({ mutationFn: api.deleteGameData, onSuccess: onSaved })
  const imported = view.data?.imported ? view.data : null
  const busy = upload.isPending || remove.isPending

  return (
    <>
      <button type="button" className="secondary" onClick={() => dialogRef.current?.showModal()}>
        {label}
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog notifications-dialog"
        aria-labelledby="game-data-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close()
        }}
      >
        <header className="weights-dialog-header">
          <h2 id="game-data-title">Import game data</h2>
          <button type="button" className="secondary" aria-label="Close" onClick={() => dialogRef.current?.close()}>
            ✕
          </button>
        </header>
        <p className="muted">
          The CharacterPlannerExport addon records your bags, bank and quest log, which Battle.net doesn't share. The
          game saves them when you log out or type <code>/reload</code>, to:
        </p>
        <p>
          <code className="file-path">{WHERE}</code>
        </p>
        <p className="muted">
          Upload that file for the character it belongs to. It replaces the last import. Only what the addon recorded is
          kept, never the file itself.
        </p>
        <label className="file-pick">
          CharacterPlannerExport.lua{' '}
          <input
            ref={inputRef}
            type="file"
            accept=".lua"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) upload.mutate(file)
              event.target.value = ''
            }}
          />
        </label>
        {upload.isPending && <p className="muted">Importing…</p>}
        {upload.isError && (
          <p className="error" role="alert">
            {upload.error.message}
          </p>
        )}
        {imported?.data && (
          <div role="status">
            <p>
              {upload.isSuccess ? 'Imported' : 'Last import'}: <strong>{imported.data.character.name}</strong>, level{' '}
              {imported.data.character.level}, saved by the game{' '}
              {imported.captured_at ? ago(parseTime(imported.captured_at)) : 'at an unknown time'}.
            </p>
            <ul className="import-summary">
              <li>Bags: {imported.data.bags ? count(imported.data.bags.items.length, 'item') : 'not recorded yet'}</li>
              <li>Bank: {imported.data.bank ? count(imported.data.bank.items.length, 'item') : 'not seen yet'}</li>
              <li>
                Quest log: {imported.data.quests ? count(imported.data.quests.log.length, 'quest') : 'not recorded yet'}
              </li>
            </ul>
          </div>
        )}
        {imported && (
          <div className="destination-actions">
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                if (window.confirm('Delete the imported game data for this character?')) remove.mutate()
              }}
            >
              Delete imported data
            </button>
          </div>
        )}
        {remove.isError && <p className="error">{remove.error.message}</p>}
      </dialog>
    </>
  )
}

function GameItemRow({ item, info }: { item: GameItem; info: GameItemInfo | undefined }) {
  const quality = info?.quality?.toLowerCase() ?? QUALITY[item.quality] ?? 'common'
  const name = info?.name ?? `Item ${item.item_id}`
  return (
    <li className="item-cell">
      <Icon url={info?.icon_url ?? null} />
      <div className={`item quality-${quality}`}>
        <ItemLink href={info?.wowhead}>{name}</ItemLink>
        {item.count > 1 && <span className="muted"> ×{item.count}</span>}
      </div>
    </li>
  )
}

function ItemsSection({
  title,
  section,
  at,
  items,
  missing,
}: {
  title: string
  section: GameItems | null
  at: string | null
  items: Record<string, GameItemInfo>
  missing: string
}) {
  const list = section ? stacked(section.items) : []
  return (
    <section aria-label={title} className="game-items">
      <h3>
        {title} <FromTheGame at={at} />
      </h3>
      {!section && <p className="muted">{missing}</p>}
      {section && list.length === 0 && <p className="muted">Empty.</p>}
      {list.length > 0 && (
        <ul className="game-item-list">
          {list.map((item) => (
            <GameItemRow key={item.item_id} item={item} info={items[String(item.item_id)]} />
          ))}
        </ul>
      )}
    </section>
  )
}

/** The Character tab's bags and bank, from the newest import (#185). */
export function GameDataPanel({
  battleNetLevel,
  levelSource,
}: {
  battleNetLevel: number | null
  /** The level planning uses (ADR 0052): the newer of the last sync and this data. */
  levelSource: PlanningLevel | null
}) {
  const view = useQuery({ queryKey: ['game-data'], queryFn: api.gameData })
  if (view.isError) return <p className="error">Couldn't load game data: {view.error.message}</p>
  const data = view.data
  if (!data) return null
  if (!data.imported || !data.data) {
    return (
      <section aria-label="From the game">
        <h2>From the game</h2>
        <p className="muted">
          Bags, bank and quest log come from the CharacterPlannerExport addon, which Battle.net can't see.{' '}
          <ImportGameDataDialog />
        </p>
      </section>
    )
  }
  const game = data.data
  const level = game.character.level
  return (
    <section aria-label="From the game">
      <div className="section-heading">
        <h2>
          From the game <FromTheGame at={data.captured_at} />
        </h2>
        <div className="heading-actions">
          <ImportGameDataDialog label="Import again" />
        </div>
      </div>
      <p className="muted">
        Level {level} in the game.
        {battleNetLevel !== null &&
          battleNetLevel !== level &&
          (levelSource?.source === 'game'
            ? ` Battle.net says ${battleNetLevel}, as of an older sync: the planner uses the game's level.`
            : ` Battle.net says ${battleNetLevel}, as of a newer sync: the planner uses that.`)}
      </p>
      <div className="panels">
        <ItemsSection
          title="Bags"
          section={game.bags}
          at={data.captured?.bags ?? null}
          items={data.items}
          missing="Not recorded yet."
        />
        <ItemsSection
          title="Bank"
          section={game.bank}
          at={data.captured?.bank ?? null}
          items={data.items}
          missing="Not seen yet: open your bank in the game, then log out or /reload, and import again."
        />
      </div>
    </section>
  )
}

/** Whether the objective's own text already shows its count, as "3/10". */
function hasCount(text: string, done: number, needed: number): boolean {
  return new RegExp(`(^|\\D)${done}/${needed}(\\D|$)`).test(text)
}

function QuestEntry({ quest }: { quest: GameQuest }) {
  return (
    <li>
      <a href={`https://www.wowhead.com/forever/quest=${quest.quest_id}`} target="_blank" rel="noreferrer">
        {quest.title}
      </a>
      {quest.complete && <span className="tag">ready to hand in</span>}
      {quest.objectives.length > 0 && (
        <ul className="objectives">
          {quest.objectives.map((objective) => (
            <li key={`${objective.type}:${objective.text}`} className={objective.finished ? 'muted' : undefined}>
              {objective.text} {/* The game writes most counts into the text ("0/10 Redridge Brute slain"). */}
              {!hasCount(objective.text, objective.done, objective.needed) && (
                <span className={objective.finished ? 'muted' : 'tag'}>
                  {objective.done}/{objective.needed}
                </span>
              )}
              {objective.finished && <span aria-label="done"> ✓</span>}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/** The Plan tab's quest log, with each objective's count (#185). */
export function QuestLog() {
  const view = useQuery({ queryKey: ['game-data'], queryFn: api.gameData })
  const data = view.data
  if (!data) return null
  const quests = data.data?.quests
  return (
    <section aria-label="Quest log">
      <h2>
        Quest log <FromTheGame at={data.captured?.quests ?? null} />
      </h2>
      {!data.imported && (
        <p className="muted">
          Your quest log comes from the CharacterPlannerExport addon. <ImportGameDataDialog />
        </p>
      )}
      {data.imported && !quests && <p className="muted">Not recorded yet.</p>}
      {quests && quests.log.length === 0 && <p className="muted">No quests in the log.</p>}
      {quests && quests.log.length > 0 && (
        <ul className="quest-log">
          {quests.log.map((quest) => (
            <QuestEntry key={quest.quest_id} quest={quest} />
          ))}
        </ul>
      )}
    </section>
  )
}
