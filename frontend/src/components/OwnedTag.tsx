import type { OwnedItem } from '../api'
import { ago, parseTime } from '../gameData'

/** "owned: in your bags": an item the game data shows you have, but aren't wearing (#186). */
export function OwnedTag({ owned }: { owned: OwnedItem | null | undefined }) {
  if (!owned) return null
  const count = owned.count > 1 ? ` ×${owned.count}` : ''
  return (
    <span
      className="tag owned"
      title={`Owned, not equipped: from the game, ${ago(parseTime(owned.captured_at))}. Go and get it.`}
    >
      owned: in your {owned.where}
      {count}
    </span>
  )
}
