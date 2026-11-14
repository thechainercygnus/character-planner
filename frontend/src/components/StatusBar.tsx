import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, selectCharacter, type SyncResult } from '../api'
import { CharacterSwitcher } from './CharacterSwitcher'
import { NotificationsDialog } from './NotificationsDialog'

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

const REFRESH_LABEL: Record<string, string> = { pool: 'the item pool', enchants: 'enchant data' }

export function StatusBar() {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  // With users on, instance-wide actions are the admin's (ADR 0037); without users, everyone's.
  const canAdminister = !me.data?.users || me.data.admin
  const signOut = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      selectCharacter(null)
      window.location.reload()
    },
  })
  // While a refresh runs (the first data load after a sync, the worker, or a button), check
  // every few seconds, and reload everything once it has finished (#87).
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
    mutationFn: api.sync,
    onSuccess: () => {
      setWatchUntil(Date.now() + 60_000)
      return queryClient.invalidateQueries()
    },
  })
  const refreshItems = useMutation({
    mutationFn: api.refreshItems,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gear'] }),
  })
  const refreshEnchants = useMutation({
    mutationFn: api.refreshEnchants,
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const refreshPool = useMutation({
    mutationFn: () => api.refreshPool(),
    onSuccess: () => queryClient.invalidateQueries(),
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
        <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? 'Syncing…' : 'Sync now'}
        </button>
      ) : (
        <span className="warn" role="alert">
          No Battle.net client: set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env to sync.
        </span>
      )}
      {status.data.character_found === false && !sync.isPending && (
        <span className="warn" role="alert">
          Battle.net can't find {status.data.character}: check its name and region. A mistyped character can be deleted
          under Privacy and added again.
        </span>
      )}
      {canAdminister && <NotificationsDialog />}
      <details className="menu">
        <summary aria-label="More actions" title="More actions">
          ⋯
        </summary>
        <div className="menu-items">
          <a
            className="button secondary"
            href="#guest"
            title="Recommendations for any class and level, without your character"
          >
            Guest mode
          </a>
          {me.data?.users && me.data.signed_in && (
            <button type="button" className="secondary" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
              Sign out
            </button>
          )}
          {canAdminister && (
            <>
              <button
                type="button"
                className="secondary"
                onClick={() => refreshItems.mutate()}
                disabled={refreshItems.isPending}
                title="Look up every gear target in Battle.net item data again"
              >
                Refresh item data
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => refreshPool.mutate()}
                disabled={refreshPool.isPending}
                title="Fetch dungeon drops and quest rewards from Forever Companion (first run takes a few minutes)"
              >
                Refresh item pool
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => refreshEnchants.mutate()}
                disabled={refreshEnchants.isPending}
                title="Fetch enchant recipes from Battle.net and their reagents from Forever Companion"
              >
                Refresh enchant data
              </button>
            </>
          )}
        </div>
      </details>
      {refreshing.length > 0 && (
        <span className="muted" role="status">
          Loading {refreshing.map((name) => REFRESH_LABEL[name] ?? name).join(' and ')} in the background…
        </span>
      )}
      {refreshItems.isPending && <span className="muted">Looking up items…</span>}
      {refreshPool.isPending && <span className="muted">Refreshing item pool… (can take a few minutes)</span>}
      {refreshEnchants.isPending && (
        <span className="muted">Fetching enchant data… (first run takes a few minutes)</span>
      )}
      {refreshEnchants.isError && (
        <span className="error">Enchant refresh failed: {refreshEnchants.error.message}</span>
      )}
      {refreshEnchants.data && (
        <span className="muted">
          Enchants: {refreshEnchants.data.recipes_listed} recipes, {refreshEnchants.data.recipes_fetched} fetched
          {refreshEnchants.data.errors.length > 0 && `, ${refreshEnchants.data.errors.length} errors`}
        </span>
      )}
      {sync.isError && <span className="error">Sync failed: {sync.error.message}</span>}
      {refreshItems.isError && <span className="error">Item lookup failed: {refreshItems.error.message}</span>}
      {refreshItems.data && (
        <span className="muted">
          Blizzard found {refreshItems.data.found.length}, Forever Companion fetched{' '}
          {refreshItems.data.companion_fetched}
          {refreshItems.data.errors.length > 0 && `, ${refreshItems.data.errors.length} errors`}
        </span>
      )}
      {refreshPool.isError && <span className="error">Pool refresh failed: {refreshPool.error.message}</span>}
      {refreshPool.data && (
        <span className="muted">
          Pool: {refreshPool.data.in_window} items in reach, {refreshPool.data.items_fetched} fetched
          {refreshPool.data.errors.length > 0 && `, ${refreshPool.data.errors.length} errors`}
        </span>
      )}
      {failed.length > 0 && <span className="warn">Not returned: {failed.join(', ')}</span>}
    </div>
  )
}
