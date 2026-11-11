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
