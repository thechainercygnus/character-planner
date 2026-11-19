import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import { api, type AlertInfo, type DiscordLink, type DiscordView } from '../api'

function Linked({
  link,
  alerts,
  onSaved,
}: {
  link: DiscordLink
  alerts: AlertInfo[]
  onSaved: (view: DiscordView) => void
}) {
  const update = useMutation({ mutationFn: api.updateDiscord, onSuccess: onSaved })
  const unlink = useMutation({ mutationFn: api.unlinkDiscord, onSuccess: onSaved })
  const test = useMutation({ mutationFn: api.testDiscord, onSuccess: onSaved })
  const busy = update.isPending || unlink.isPending || test.isPending
  const error = update.error ?? unlink.error ?? test.error

  return (
    <fieldset className="destination">
      <legend>
        Linked to <strong>{link.name}</strong>
      </legend>
      <label>
        <input
          type="checkbox"
          checked={link.enabled}
          disabled={busy}
          onChange={(event) => update.mutate({ enabled: event.target.checked })}
        />{' '}
        Send me DMs
      </label>
      <div className="rule-types">
        {alerts.map((alert) => (
          <label key={alert.kind}>
            <input
              type="checkbox"
              checked={link.alerts.includes(alert.kind)}
              disabled={busy}
              onChange={(event) =>
                update.mutate({
                  alerts: event.target.checked
                    ? [...link.alerts, alert.kind]
                    : link.alerts.filter((k) => k !== alert.kind),
                })
              }
            />{' '}
            {alert.label}
          </label>
        ))}
      </div>
      {link.last_error && (
        <p className="error" role="alert">
          {link.last_error}
        </p>
      )}
      <div className="destination-actions">
        <button type="button" className="secondary" disabled={busy} onClick={() => test.mutate()}>
          {test.isPending ? 'Sending…' : 'Send a test DM'}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Unlink ${link.name}? Its id and name are deleted, and DMs stop.`)) unlink.mutate()
          }}
        >
          Unlink Discord
        </button>
        {test.isSuccess && !link.last_error && <span className="muted">Test sent. Check your DMs.</span>}
      </div>
      {error && <p className="error">{error.message}</p>}
    </fieldset>
  )
}

/**
 * The user's own Discord DM settings (#58, ADR 0044): link an account, choose alerts, test,
 * unlink. Shared by the header's Discord dialog and the account page (#217). Nothing when the
 * instance has no bot.
 */
export function DiscordSettings() {
  const queryClient = useQueryClient()
  const view = useQuery({ queryKey: ['discord'], queryFn: api.discord })
  const onSaved = (saved: DiscordView) => queryClient.setQueryData(['discord'], saved)
  const data = view.data
  if (!data?.available) return null
  const invite = data.invite_url && (
    <a href={data.invite_url} target="_blank" rel="noreferrer">
      Join the planner's Discord server
    </a>
  )
  return (
    <>
      <p className="muted">
        Get your characters' alerts as private messages from the planner's bot: level-ups, targets reached or now in
        reach, and upgrades worth having. At most one DM a sync. The bot can only message you while you're in its server
        and allow direct messages from its members.
      </p>
      {data.linked ? (
        <Linked link={data.linked} alerts={data.alerts} onSaved={onSaved} />
      ) : (
        <p>
          <a className="button" href="/auth/discord/login">
            Link Discord
          </a>{' '}
          <span className="muted">Discord tells the planner your account's id and name, nothing else.</span>
        </p>
      )}
      {data.in_server === false && (
        <p className="warn" role="status">
          You're not in the bot's server, so it can't message you. {invite}
        </p>
      )}
      {data.in_server !== false && invite && <p className="muted">{invite}</p>}
    </>
  )
}

/**
 * Status bar: "Discord" opens the user's own Discord DM settings (#58, ADR 0044) in a dialog.
 * Not shown when the instance has no bot.
 */
export function DiscordDialog() {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const view = useQuery({ queryKey: ['discord'], queryFn: api.discord })
  if (!view.data?.available) return null

  return (
    <>
      <button type="button" className="secondary" onClick={() => dialogRef.current?.showModal()}>
        Discord
      </button>
      <dialog
        ref={dialogRef}
        className="weights-dialog notifications-dialog"
        aria-labelledby="discord-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close()
        }}
      >
        <header className="weights-dialog-header">
          <h2 id="discord-title">Discord DMs</h2>
          <button type="button" className="secondary" aria-label="Close" onClick={() => dialogRef.current?.close()}>
            ✕
          </button>
        </header>
        <DiscordSettings />
      </dialog>
    </>
  )
}
