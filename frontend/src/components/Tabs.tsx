import { useEffect, useState } from 'react'

export interface Tab<Id extends string> {
  id: Id
  label: string
}

function fromHash<Id extends string>(tabs: readonly Tab<Id>[], fallback: Id): Id {
  const wanted = window.location.hash.replace(/^#/, '')
  return tabs.find((tab) => tab.id === wanted)?.id ?? fallback
}

/** The selected tab, kept in the URL hash so reloads and bookmarks keep it. */
export function useHashTab<Id extends string>(tabs: readonly Tab<Id>[], fallback: Id) {
  const [active, setActive] = useState<Id>(() => fromHash(tabs, fallback))

  useEffect(() => {
    const onHashChange = () => setActive(fromHash(tabs, fallback))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [tabs, fallback])

  const select = (id: Id) => {
    // replaceState: switching tabs shouldn't fill the back button's history.
    window.history.replaceState(null, '', `#${id}`)
    setActive(id)
  }
  return [active, select] as const
}

export function TabBar<Id extends string>({
  tabs,
  active,
  onSelect,
  counts = {},
}: {
  tabs: readonly Tab<Id>[]
  active: Id
  onSelect: (id: Id) => void
  counts?: Partial<Record<Id, number>>
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
