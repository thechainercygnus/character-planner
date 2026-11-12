import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type SyncResult } from '../api'

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

export function StatusBar() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const sync = useMutation({
    mutationFn: api.sync,
    onSuccess: () => queryClient.invalidateQueries(),
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
    mutationFn: api.refreshPool,
    onSuccess: () => queryClient.invalidateQueries(),
  })

  if (status.isPending) return <div className="status-bar">Checking login…</div>
  if (status.isError) {
    return <div className="status-bar error">Backend unreachable: {status.error.message}</div>
  }

  const loggedIn = status.data.logged_in
  const failed = sync.data ? failures(sync.data) : []

  return (
    <div className="status-bar">
      <span>Last sync: {lastSynced(status.data.latest_snapshots)}</span>
      {loggedIn ? (
        <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? 'Syncing…' : 'Sync now'}
        </button>
      ) : (
        <a className="button" href="/auth/login">
          Log in with Battle.net
        </a>
      )}
      <details className="menu">
        <summary aria-label="More actions" title="More actions">
          ⋯
        </summary>
        <div className="menu-items">
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
        </div>
      </details>
      {refreshItems.isPending && <span className="muted">Looking up items…</span>}
      {refreshPool.isPending && <span className="muted">Refreshing item pool… (can take a few minutes)</span>}
      {refreshEnchants.isPending && <span className="muted">Fetching enchant data… (first run takes a few minutes)</span>}
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
      {refreshItems.isError && (
        <span className="error">Item lookup failed: {refreshItems.error.message}</span>
      )}
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
