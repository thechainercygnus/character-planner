import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type AlertInfo, type Audience, type Destination, type NotificationsView, type SendResult } from '../api'

function when(timestamp: string | null): string {
  if (!timestamp) return '—'
  // Backend timestamps are UTC without an offset.
  const date = new Date(timestamp.endsWith('Z') || timestamp.includes('+') ? timestamp : `${timestamp}Z`)
  return date.toLocaleString()
}

/** One destination: on/off, its alerts, a test send and removal. */
function DestinationRow({
  destination,
  alerts,
  onSaved,
}: {
  destination: Destination
  alerts: AlertInfo[]
  onSaved: (view: NotificationsView) => void
}) {
  const update = useMutation({ mutationFn: api.updateDestination, onSuccess: onSaved })
  const remove = useMutation({ mutationFn: api.removeDestination, onSuccess: onSaved })
  const [tested, setTested] = useState<SendResult | null>(null)
  const test = useMutation({ mutationFn: api.testDestination, onSuccess: setTested })
  const offered = alerts.filter((a) => destination.audience === 'user' || a.audience === 'system')
  const busy = update.isPending || remove.isPending || test.isPending
  const label = `${destination.name} (${destination.audience})`

  return (
    <fieldset className="destination">
      <legend>
        {destination.name} <span className="badge">{destination.audience === 'system' ? 'system' : 'user'}</span>{' '}
        <span className="muted">{destination.url}</span>
      </legend>
      <label>
        <input
          type="checkbox"
          aria-label={`${label} enabled`}
          checked={destination.enabled}
          disabled={busy}
          onChange={(event) => update.mutate({ id: destination.id, enabled: event.target.checked })}
        />{' '}
        Enabled
      </label>
      <div className="rule-types">
        {offered.map((alert) => (
          <label key={alert.kind}>
            <input
              type="checkbox"
              aria-label={`${label} ${alert.label}`}
              checked={destination.alerts.includes(alert.kind)}
              disabled={busy}
              onChange={(event) =>
                update.mutate({
                  id: destination.id,
                  alerts: event.target.checked
                    ? [...destination.alerts, alert.kind]
                    : destination.alerts.filter((k) => k !== alert.kind),
                })
              }
            />{' '}
            {alert.label}
            {alert.audience === 'system' && <span className="muted"> (system)</span>}
          </label>
        ))}
      </div>
      <div className="destination-actions">
        <button type="button" className="secondary" disabled={busy} onClick={() => test.mutate(destination.id)}>
          {test.isPending ? 'Sending…' : 'Send a test'}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Remove ${destination.name}? Its queued alerts are dropped.`)) remove.mutate(destination.id)
          }}
        >
          Remove
        </button>
        {tested?.ok && <span className="muted">Test sent. Check the channel.</span>}
        {tested && !tested.ok && (
          <span className="error">
            Test failed: {tested.error}
            {tested.gone && '. The webhook may have been deleted'}
          </span>
        )}
        {!tested && destination.last_error && <span className="error">Last error: {destination.last_error}</span>}
        {!tested && !destination.last_error && destination.last_sent_at && (
          <span className="muted">Last sent {when(destination.last_sent_at)}</span>
        )}
      </div>
      {(update.isError || remove.isError) && (
        <p className="error">{(update.error ?? remove.error)?.message}</p>
      )}
    </fieldset>
  )
}

/**
 * Status bar: "Alerts" opens the notification settings (#12, ADR 0021): Discord webhook
 * destinations, which alerts each one gets, test sends and what was sent recently.
 */
export function NotificationsDialog() {
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const view = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, enabled: open })
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [audience, setAudience] = useState<Audience>('user')

  const onSaved = (saved: NotificationsView) => queryClient.setQueryData(['notifications'], saved)
  const add = useMutation({
    mutationFn: api.addDestination,
    onSuccess: (saved) => {
      onSaved(saved)
      setName('')
      setUrl('')
    },
  })
  const data = view.data

  return (
    <>
      <button
        type="button"
        className="secondary"
        onClick={() => {
          setOpen(true)
          dialogRef.current?.showModal()
        }}
      >
        Alerts
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog notifications-dialog"
        aria-labelledby="notifications-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close()
        }}
      >
        <header className="weights-dialog-header">
          <h2 id="notifications-title">Alerts</h2>
          <button type="button" className="secondary" aria-label="Close" onClick={() => dialogRef.current?.close()}>
            ✕
          </button>
        </header>
        <p className="muted">
          Get alerts in Discord: level-ups, targets reached or now in reach, and upgrades worth having. In Discord, open a channel's settings, then <strong>Integrations → Webhooks → New
          Webhook</strong>, copy its URL and paste it below. Anyone with that URL can post to the channel, so it's
          kept private: it's never shown again in full.
        </p>
        {view.isPending && <p className="muted">Loading…</p>}
        {view.isError && <p className="error">Couldn't load alerts: {view.error.message}</p>}

        {data && (
          <>
            {data.destinations.length === 0 && <p>No destinations yet.</p>}
            {data.destinations.map((destination) => (
              <DestinationRow key={destination.id} destination={destination} alerts={data.alerts} onSaved={onSaved} />
            ))}
            {data.destinations.length > 0 && data.system_alerts_to_user && (
              <p className="muted">
                System alerts (failed jobs, upstream errors) go to your destinations while there's no system
                destination.
              </p>
            )}

            <form
              className="add-destination"
              onSubmit={(event) => {
                event.preventDefault()
                add.mutate({ name, url, audience })
              }}
            >
              <h3>Add a destination</h3>
              <label>
                Name{' '}
                <input value={name} maxLength={60} placeholder="My alerts" onChange={(e) => setName(e.target.value)} />
              </label>
              <label>
                Webhook URL{' '}
                <input
                  value={url}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="https://discord.com/api/webhooks/…"
                  onChange={(e) => setUrl(e.target.value)}
                />
              </label>
              <label>
                For{' '}
                <select value={audience} onChange={(e) => setAudience(e.target.value as Audience)}>
                  <option value="user">My character's alerts</option>
                  <option value="system">System alerts only (whoever runs this instance)</option>
                </select>
              </label>
              <button type="submit" disabled={add.isPending || !name.trim() || !url.trim()}>
                {add.isPending ? 'Adding…' : 'Add'}
              </button>
              {add.isError && <span className="error">{add.error.message}</span>}
            </form>

            {data.recent.length > 0 && (
              <>
                <h3>Recent alerts</h3>
                <table className="gear recent-alerts">
                  <thead>
                    <tr>
                      <th>Queued</th>
                      <th>To</th>
                      <th>Alert</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.map((alert, index) => (
                      // A read-only list in a fixed order with no id: its index is stable.
                      // oxlint-disable-next-line react/no-array-index-key
                      <tr key={index}>
                        <td>{when(alert.created_at)}</td>
                        <td>{alert.destination}</td>
                        <td>{data.alerts.find((a) => a.kind === alert.kind)?.label ?? alert.kind}</td>
                        <td>
                          {alert.sent_at
                            ? `sent ${when(alert.sent_at)}`
                            : alert.failed
                              ? `failed: ${alert.last_error ?? '?'}`
                              : `waiting${alert.attempts ? ` (${alert.attempts} tries: ${alert.last_error})` : ''}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </dialog>
    </>
  )
}
