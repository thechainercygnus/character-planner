import type { Tab } from '../useHashTab'

// A default prop made once, not on every render (oxlint react/no-object-type-as-default-prop).
const NO_COUNTS = {}

export function TabBar<Id extends string>({
  tabs,
  active,
  onSelect,
  counts = NO_COUNTS,
}: {
  tabs: readonly Tab<Id>[]
  active: Id
  onSelect: (id: Id) => void
  counts?: Partial<Record<Id, number | undefined>>
}) {
  return (
    <nav className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          className={tab.id === active ? 'tab active' : 'tab'}
          onClick={() => onSelect(tab.id)}
        >
          {tab.label}
          {counts[tab.id] !== undefined && <span className="tab-count">{counts[tab.id]}</span>}
        </button>
      ))}
    </nav>
  )
}
