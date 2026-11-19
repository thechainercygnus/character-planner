import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError, canAdmin, selectCharacter, type SyncResult } from '../api'
import { CharacterSwitcher } from './CharacterSwitcher'

function lastSynced(snapshots: Record<string, string>): string {
  const times = Object.values(snapshots)
  if (times.length === 0) return 'never'
  const newest = times.reduce((a, b) => (a > b ? a : b))
  // Backend timestamps are UTC without an offset; mark them as UTC before parsing.
  const date = new Date(newest.endsWith('Z') || newest.includes('+') ? newest : `${newest}Z`)
  return date.toLocaleString()
}

function failures(result: SyncResult): string[] {
  return Object.entries(result)
    .filter(([, status]) => status < 200 || status >= 300)
    .map(([kind, status]) => `${kind} (${status})`)
}

const REFRESH_LABEL: Record<string, string> = {
  pool: 'the item pool',
  enchants: 'enchant data',
  'game-items': 'item names and icons for your game data', // after an import (#185)
  recipes: 'recipes for your professions', // after a sync (#226)
}

/**
 * The bar above every tab (#260): the character, its last sync and Sync now, then My account,
 * Admin and Sign out. Everything else lives on those pages: the alerts and Discord DMs on My
 * account, the instance's refreshes on Admin.
 */
export function StatusBar() {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const signOut = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      selectCharacter(null)
      window.location.reload()
    },
  })
  // While a refresh runs (the first data load after a sync, the worker, or Admin's buttons),
  // check every few seconds, and reload everything once it has finished (#87).
  // After a sync, watch for a minute: a first sync starts loading data in the background.
  const [watchUntil, setWatchUntil] = useState(0)
  const status = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: (query) =>
      (query.state.data?.refreshing.length ?? 0) > 0 || Date.now() < watchUntil ? 5000 : false,
  })
  const refreshing = status.data?.refreshing ?? []
  const wasRefreshing = useRef(false)
  useEffect(() => {
    if (refreshing.length > 0) {
      wasRefreshing.current = true
    } else if (wasRefreshing.current) {
      wasRefreshing.current = false
      void queryClient.invalidateQueries()
    }
  }, [refreshing.length, queryClient])
  const sync = useMutation({
    mutationFn: () => api.sync(),
    onSuccess: () => {
      setWatchUntil(Date.now() + 60_000)
      return queryClient.invalidateQueries()
    },
  })

  if (status.isPending) return <div className="status-bar">Checking status…</div>
  if (status.isError) {
    return <div className="status-bar error">Backend unreachable: {status.error.message}</div>
  }

  const failed = sync.data ? failures(sync.data) : []

  // Syncs use the app's own Battle.net token, so no login is needed (#107): only the client
  // in .env, and a character Battle.net can find.
  return (
    <div className="status-bar">
      <CharacterSwitcher />
      <span>Last sync: {lastSynced(status.data.latest_snapshots)}</span>
      {status.data.can_sync ? (
        // Nothing to sync on a blank instance (#206): the switcher offers to add one.
        status.data.character !== null && (
          <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? 'Syncing…' : 'Sync now'}
          </button>
        )
      ) : (
        <span className="warn" role="alert">
          No Battle.net client: set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env to sync.
        </span>
      )}
      <nav className="account-links" aria-label="Account">
        <a className="button secondary" href="#account" title="Your characters, guilds, alerts and data">
          My account
        </a>
        {canAdmin(me.data) && (
          <a className="button secondary" href="#admin" title="This instance: its data, health and backups">
            Admin
          </a>
        )}
        {me.data?.users && me.data.signed_in && (
          <button type="button" className="secondary" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
            Sign out
          </button>
        )}
      </nav>
      {status.data.character_found === false && !sync.isPending && (
        <span className="warn" role="alert">
          Battle.net can't find {status.data.character}. It only shares characters at level 10; below that, sync again
          once it's there. Otherwise check its name and region: a mistyped character can be removed on My account and
          added again.
        </span>
      )}
      {refreshing.length > 0 && (
        <span className="muted" role="status">
          Loading {refreshing.map((name) => REFRESH_LABEL[name] ?? name).join(' and ')} in the background…
        </span>
      )}
      {sync.isError &&
        (sync.error instanceof ApiError && sync.error.status === 429 ? (
          <span className="muted">{sync.error.message}</span>
        ) : (
          <span className="error">Sync failed: {sync.error.message}</span>
        ))}
      {failed.length > 0 && <span className="warn">Not returned: {failed.join(', ')}</span>}
    </div>
  )
}
