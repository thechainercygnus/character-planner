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
      <button
        type="button"
        className="secondary"
        onClick={() => refreshItems.mutate()}
        disabled={refreshItems.isPending}
        title="Look up every gear target in Battle.net item data again"
      >
        {refreshItems.isPending ? 'Looking up items…' : 'Refresh item data'}
      </button>
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
      {failed.length > 0 && <span className="warn">Not returned: {failed.join(', ')}</span>}
    </div>
  )
}
