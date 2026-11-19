import type { QuestProgress } from '../api'
import { ago, parseTime } from '../gameData'

/**
 * A quest's state from the game data (#186): done, ready to hand in, or how far along it is
 * in the log. Nothing when the game data doesn't know the quest.
 */
export function QuestTag({
  progress,
  completed = false,
  named = false,
}: {
  progress: QuestProgress | null | undefined
  completed?: boolean
  /** Say which quest: for a target, whose reward quest isn't otherwise shown. */
  named?: boolean
}) {
  if (completed) return <span className="tag done">done</span>
  if (!progress) return null
  const title = `${progress.title}, in your quest log: from the game, ${ago(parseTime(progress.captured_at))}`
  const quest = named ? `${progress.title}: ` : ''
  if (progress.complete) {
    return (
      <span className="tag owned" title={title}>
        {quest}ready to hand in
      </span>
    )
  }
  const count = progress.needed > 0 ? ` ${progress.done}/${progress.needed}` : ''
  return (
    <span className="tag" title={title}>
      {quest}in your log{count}
    </span>
  )
}
