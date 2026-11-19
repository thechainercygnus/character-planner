import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  api,
  ApiError,
  can,
  canAdmin,
  inviteLink,
  isQueued,
  type Account,
  type AdminLogEntry,
  type AdminView,
  type InviteView,
} from '../api'

const ROLE_LABEL: Record<string, string> = { admin: 'Admin', superuser: 'Superuser', user: 'User' }

function day(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString()
}

/** The admin makes a user a superuser, or a user again; the admin's own role never changes. */
function RoleCell({ account, canManage }: { account: Account; canManage: boolean }) {
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: api.setRole,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-accounts'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-log'] })
    },
  })
  const label = ROLE_LABEL[account.role] ?? account.role
  if (!canManage || account.role === 'admin') return <>{label}</>
  return (
    <>
      <select
        aria-label={`Role of account ${account.account_id}`}
        value={account.role}
        disabled={change.isPending}
        onChange={(event) => change.mutate({ userId: account.user_id, role: event.target.value })}
      >
        <option value="user">User</option>
        <option value="superuser">Superuser</option>
      </select>
      {change.isError && <small className="error"> {change.error.message}</small>}
    </>
  )
}

/**
 * Delete an account and everything stored for it (#238): only once its Battle.net account id
 * is typed in, as the server checks too.
 */
function DeleteAccount({ account }: { account: Account }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const remove = useMutation({
    mutationFn: api.deleteUser,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-accounts'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-log'] })
    },
  })
  if (!open) {
    return (
      <button type="button" className="secondary" onClick={() => setOpen(true)}>
        Delete…
      </button>
    )
  }
  return (
    <form
      className="confirm-delete"
      onSubmit={(event) => {
        event.preventDefault()
        remove.mutate({ userId: account.user_id, confirm: account.account_id })
      }}
    >
      <label>
        Type {account.account_id} to delete this account and everything stored for it. This can't be undone.{' '}
        <input
          inputMode="numeric"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          aria-label={`Type ${account.account_id} to confirm`}
        />
      </label>{' '}
      <button type="submit" disabled={typed.trim() !== String(account.account_id) || remove.isPending}>
        Delete for good
      </button>{' '}
      <button type="button" className="secondary" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {remove.isError && <p className="error">{remove.error.message}</p>}
    </form>
  )
}

function DataRequests({ account, me }: { account: Account; me: Requests }) {
  return (
    <div className="data-requests">
      {me.canExport && (
        <a className="button secondary" href={api.exportUrl(account.user_id)} download>
          Export
        </a>
      )}{' '}
      {me.canDelete && account.role !== 'admin' && <DeleteAccount account={account} />}
    </div>
  )
}

type Requests = { canExport: boolean; canDelete: boolean }

function Accounts({ view, canManage, requests }: { view: AdminView; canManage: boolean; requests: Requests }) {
  const asks = requests.canExport || requests.canDelete
  return (
    <section>
      <h2>Accounts</h2>
      <p className="muted">
        What the planner stores about each account, and no more: it's for running the instance, not watching people.
      </p>
      <table className="gear">
        <thead>
          <tr>
            <th scope="col">Battle.net account</th>
            <th scope="col">Role</th>
            <th scope="col">Characters</th>
            <th scope="col">Signed up</th>
            <th scope="col">Last sign-in</th>
            {asks && <th scope="col">Data requests</th>}
          </tr>
        </thead>
        <tbody>
          {view.accounts.map((account) => (
            <tr key={account.user_id}>
              <td>{account.account_id}</td>
              <td>
                <RoleCell account={account} canManage={canManage} />
              </td>
              <td>
                {account.characters.length > 0 ? (
                  account.characters.map((c) => `${c.name} (${c.region.toUpperCase()})`).join(', ')
                ) : (
                  <span className="muted">none</span>
                )}
              </td>
              <td>{day(account.created_at)}</td>
              <td>{day(account.last_sign_in_at)}</td>
              {asks && (
                <td>
                  <DataRequests account={account} me={requests} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Roles({ view }: { view: AdminView }) {
  return (
    <section>
      <h2>Roles</h2>
      <p className="muted">The admin may do everything. Only the admin makes someone a superuser.</p>
      <ul className="roles">
        {view.roles.map((role) => (
          <li key={role.name}>
            <strong>{ROLE_LABEL[role.name] ?? role.name}</strong>
            {role.permissions.length > 0 ? (
              <ul>
                {role.permissions.map((permission) => (
                  <li key={permission}>{view.permissions[permission] ?? permission}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">Their own characters and settings only.</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

const INVITE_STATE: Record<InviteView['state'], string> = {
  open: 'open',
  used: 'used',
  revoked: 'revoked',
  expired: 'expired',
}

function InviteRow({ invite }: { invite: InviteView }) {
  const queryClient = useQueryClient()
  const revoke = useMutation({
    mutationFn: api.revokeInvite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-signups'] }),
  })
  return (
    <li>
      Made {day(invite.created_at)}: <strong>{INVITE_STATE[invite.state]}</strong>
      {invite.state === 'open' && <> · valid until {day(invite.expires_at)}</>}
      {invite.state === 'used' && invite.used_by_account_id !== null && (
        <>
          {' '}
          by account {invite.used_by_account_id}
          {invite.used_at && <> on {day(invite.used_at)}</>}
        </>
      )}
      {invite.state === 'open' && (
        <>
          {' '}
          <button
            type="button"
            className="secondary"
            onClick={() => revoke.mutate(invite.id)}
            disabled={revoke.isPending}
            aria-label={`Revoke the invite made ${day(invite.created_at)}`}
          >
            Revoke
          </button>
        </>
      )}
      {revoke.isError && <small className="error"> {revoke.error.message}</small>}
    </li>
  )
}

/**
 * Sign-ups (#239, ADR 0057): open or close them, which wins over PLANNER_SIGNUPS from then
 * on, and invite one person at a time while they're closed.
 */
function Signups() {
  const queryClient = useQueryClient()
  const view = useQuery({ queryKey: ['admin-signups'], queryFn: api.adminSignups })
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin-signups'] })
    await queryClient.invalidateQueries({ queryKey: ['admin-log'] })
    await queryClient.invalidateQueries({ queryKey: ['me'] })
  }
  const toggle = useMutation({ mutationFn: api.setSignups, onSuccess: refresh })
  const invite = useMutation({ mutationFn: api.createInvite, onSuccess: refresh })
  const [copied, setCopied] = useState(false)
  if (view.isError) return <p className="error">Couldn't load sign-ups: {view.error.message}</p>
  if (!view.data) return null
  const { signups, setting, invites } = view.data
  const link = invite.data ? inviteLink(invite.data.token) : null
  return (
    <section>
      <h2>Sign-ups</h2>
      <p>
        Sign-ups are <strong>{signups.open ? 'open' : 'closed'}</strong>
        {signups.source === 'app'
          ? `, as set here${signups.changed_at ? ` on ${day(signups.changed_at)}` : ''}. PLANNER_SIGNUPS no longer applies.`
          : `, from PLANNER_SIGNUPS (${setting ? 'on' : 'off'}). A change here wins from then on.`}{' '}
        <button
          type="button"
          className="secondary"
          onClick={() => toggle.mutate(!signups.open)}
          disabled={toggle.isPending}
        >
          {signups.open ? 'Close sign-ups' : 'Open sign-ups'}
        </button>
      </p>
      {toggle.isError && <p className="error">{toggle.error.message}</p>}

      <h3>Invites</h3>
      <p className="muted">
        A link that lets one person sign up while sign-ups are closed: it works once, for 7 days, and can be revoked.
      </p>
      <p>
        <button type="button" onClick={() => invite.mutate()} disabled={invite.isPending}>
          Make an invite link
        </button>
      </p>
      {invite.isError && <p className="error">{invite.error.message}</p>}
      {link && (
        <div className="invite-link" role="status">
          <p>Send this link to the person you're inviting. It's shown only now:</p>
          <input readOnly value={link} aria-label="Invite link" onFocus={(event) => event.target.select()} />{' '}
          <button
            type="button"
            className="secondary"
            onClick={() => {
              void navigator.clipboard?.writeText(link).then(() => setCopied(true))
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}
      {invites.length > 0 && (
        <ul className="invites">
          {invites.map((row) => (
            <InviteRow key={row.id} invite={row} />
          ))}
        </ul>
      )}
    </section>
  )
}

function size(bytes: number | null): string {
  if (bytes === null) return '?'
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} kB`
}

/**
 * Encrypted backups (#240, ADR 0061): whether they're set up, the last one's outcome, and a
 * button to back up now. Restoring is a command, and needs the age private key, which the
 * server never has.
 */
function Backups() {
  const queryClient = useQueryClient()
  const view = useQuery({ queryKey: ['admin-backups'], queryFn: api.adminBackups })
  const now = useMutation({
    mutationFn: api.backUpNow,
    onSuccess: async (saved) => {
      queryClient.setQueryData(['admin-backups'], saved)
      await queryClient.invalidateQueries({ queryKey: ['admin-log'] })
    },
    onError: () => queryClient.invalidateQueries({ queryKey: ['admin-backups'] }),
  })
  if (view.isError) return <p className="error">Couldn't load backups: {view.error.message}</p>
  if (!view.data) return null
  const { configured, every_hours, keep, bucket, last } = view.data
  return (
    <section>
      <h2>Backups</h2>
      {!configured ? (
        <p className="muted">
          Not set up. Set BACKUP_S3_* and BACKUP_AGE_RECIPIENT to back up to S3-compatible storage, encrypted with your
          age public key: see the self-hosting guide.
        </p>
      ) : (
        <>
          <p className="muted">
            Every {every_hours === 1 ? 'hour' : `${every_hours} hours`} to {bucket}, encrypted; the newest {keep} kept.
            Battle.net's data is left out: the next sync fetches it again after a restore.
          </p>
          {last === null && <p>No backup yet.</p>}
          {last?.ok && (
            <p role="status">
              Last backup {new Date(last.at).toLocaleString()}: {last.rows} rows, {size(last.size)}, {last.kept} kept.
            </p>
          )}
          {last && !last.ok && (
            <p className="error" role="alert">
              The last backup failed {new Date(last.at).toLocaleString()}: {last.error}
            </p>
          )}
          <p>
            <button type="button" onClick={() => now.mutate()} disabled={now.isPending}>
              {now.isPending ? 'Backing up…' : 'Back up now'}
            </button>
          </p>
          {now.isError && <p className="error">{now.error.message}</p>}
        </>
      )}
    </section>
  )
}

const when = (moment: string | null) => (moment ? new Date(moment).toLocaleString() : 'never')

/**
 * What /api/readyz and the metrics know (#241): the database, the queue, failed jobs, the
 * upstream budget and the shared catalogs' refreshes. Read directly, so no METRICS_TOKEN.
 */
function Health() {
  const view = useQuery({ queryKey: ['admin-health'], queryFn: api.adminHealth })
  if (view.isError) return <p className="error">Couldn't load instance health: {view.error.message}</p>
  if (!view.data) return null
  const { database, queue, failures, budgets, refreshes, leases } = view.data
  return (
    <section>
      <h2>Instance health</h2>
      <ul>
        <li>
          Database:{' '}
          {!database.reachable ? (
            <span className="error">not reachable</span>
          ) : database.migrated ? (
            'reachable, at the newest migration'
          ) : (
            <span className="error">reachable, but not at the newest migration</span>
          )}
        </li>
        <li>
          Queue:{' '}
          {!queue.configured ? (
            'not set up (REDIS_URL): syncs run in the request'
          ) : !queue.reachable ? (
            <span className="error">Redis not reachable</span>
          ) : (
            `${queue.queued} waiting, ${queue.started} running, ${queue.failed} failed; ${queue.workers} ${
              queue.workers === 1 ? 'worker' : 'workers'
            }, last heartbeat ${when(queue.last_heartbeat)}`
          )}
        </li>
      </ul>
      <h3>Upstream budget</h3>
      {budgets.length === 0 ? (
        <p className="muted">No budgets.</p>
      ) : (
        <ul>
          {budgets.map((budget) => (
            <li key={`${budget.upstream}-${budget.window_seconds}`}>
              {budget.upstream}, per {budget.window_seconds === 1 ? 'second' : `${budget.window_seconds} seconds`}:{' '}
              {budget.used} of {budget.limit} used
              {budget.waiting && <strong> (full: calls are waiting for room)</strong>}
            </li>
          ))}
        </ul>
      )}
      <h3>Refreshes</h3>
      <ul>
        {refreshes.map((refresh) => (
          <li key={refresh.name}>
            {refresh.name}: last refreshed {when(refresh.last)}
          </li>
        ))}
      </ul>
      {leases.length > 0 && <p>Running now: {leases.map((lease) => lease.name).join(', ')}.</p>}
      <h3>Recent job failures</h3>
      {failures.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul>
          {failures.map((failure) => (
            <li key={`${failure.job}-${failure.at}-${failure.error}`}>
              {failure.job}, {when(failure.at)}: {failure.error}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** A refresh the job queue will run (#17): the status bar's "Loading … in the background" follows it. */
function Queued() {
  return <p className="muted">Queued: it runs in the background.</p>
}

/** A refresh that failed, or is cooling down (429, #17): the cooldown isn't a failure. */
function Failure({ what, error }: { what: string; error: Error }) {
  if (error instanceof ApiError && error.status === 429) return <p className="muted">{error.message}</p>
  return (
    <p className="error">
      {what} failed: {error.message}
    </p>
  )
}

/**
 * The data every character shares (#260, moved from the status bar's menu): item data, the
 * item pool and enchants, refreshed now rather than on the worker's schedule; and the Discord
 * bot's pinned sign-up message (#192). `data.refresh` and `discord.signup`.
 */
function SharedData({ canRefresh, canSignup }: { canRefresh: boolean; canSignup: boolean }) {
  const queryClient = useQueryClient()
  const refreshItems = useMutation({
    mutationFn: api.refreshItems,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gear'] }),
  })
  const refreshPool = useMutation({
    mutationFn: () => api.refreshPool(),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const refreshEnchants = useMutation({
    mutationFn: api.refreshEnchants,
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const discord = useQuery({ queryKey: ['discord'], queryFn: api.discord, enabled: canSignup })
  const signupMessage = useMutation({ mutationFn: api.updateSignupMessage })
  const signup = canSignup && discord.data?.signup_message
  if (!canRefresh && !signup) return null
  return (
    <section className="shared-data">
      <h2>Shared data</h2>
      {canRefresh && (
        <>
          <p className="muted">
            Item data, the item pool and enchants are shared by every character here. The worker refreshes them on a
            schedule; refresh one now after an update to the game or to Forever Companion.
          </p>
          <p className="row-actions">
            <button
              type="button"
              className="secondary"
              onClick={() => refreshItems.mutate()}
              disabled={refreshItems.isPending}
              title="Look up every gear target in Battle.net item data again"
            >
              {refreshItems.isPending ? 'Looking up items…' : 'Refresh item data'}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => refreshPool.mutate()}
              disabled={refreshPool.isPending}
              title="Fetch dungeon drops and quest rewards from Forever Companion (first run takes a few minutes)"
            >
              {refreshPool.isPending ? 'Refreshing the pool…' : 'Refresh item pool'}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => refreshEnchants.mutate()}
              disabled={refreshEnchants.isPending}
              title="Fetch enchant recipes from Battle.net and their reagents from Forever Companion"
            >
              {refreshEnchants.isPending ? 'Fetching enchants…' : 'Refresh enchant data'}
            </button>
          </p>
          {refreshPool.isPending && <p className="muted">The item pool's first run takes a few minutes.</p>}
          {refreshItems.isError && <Failure what="Item lookup" error={refreshItems.error} />}
          {isQueued(refreshItems.data) && <Queued />}
          {refreshItems.data && !isQueued(refreshItems.data) && (
            <p className="muted">
              Items: Blizzard found {refreshItems.data.found.length}, Forever Companion fetched{' '}
              {refreshItems.data.companion_fetched}
              {refreshItems.data.errors.length > 0 && `, ${refreshItems.data.errors.length} errors`}.
            </p>
          )}
          {refreshPool.isError && <Failure what="Pool refresh" error={refreshPool.error} />}
          {isQueued(refreshPool.data) && <Queued />}
          {refreshPool.data && !isQueued(refreshPool.data) && (
            <p className="muted">
              Pool: {refreshPool.data.in_window} items in reach, {refreshPool.data.items_fetched} fetched
              {refreshPool.data.errors.length > 0 && `, ${refreshPool.data.errors.length} errors`}.
            </p>
          )}
          {refreshEnchants.isError && <Failure what="Enchant refresh" error={refreshEnchants.error} />}
          {isQueued(refreshEnchants.data) && <Queued />}
          {refreshEnchants.data && !isQueued(refreshEnchants.data) && (
            <p className="muted">
              Enchants: {refreshEnchants.data.recipes_listed} recipes, {refreshEnchants.data.recipes_fetched} fetched
              {refreshEnchants.data.errors.length > 0 && `, ${refreshEnchants.data.errors.length} errors`}.
            </p>
          )}
        </>
      )}
      {signup && (
        <>
          <h3>Discord sign-up message</h3>
          <p>
            <button
              type="button"
              className="secondary"
              onClick={() => signupMessage.mutate()}
              disabled={signupMessage.isPending}
              title="Post, or bring up to date, the bot's pinned sign-up message in DISCORD_SIGNUP_CHANNEL_ID"
            >
              Update the Discord sign-up message
            </button>
          </p>
          {signupMessage.isError && <Failure what="The sign-up message" error={signupMessage.error} />}
          {signupMessage.data && (
            <p className={signupMessage.data.ok ? 'muted' : 'error'} role="status">
              {signupMessage.data.ok
                ? `Sign-up message ${signupMessage.data.action} in Discord.`
                : `The sign-up message wasn't updated: ${signupMessage.data.error}`}
            </p>
          )}
        </>
      )}
    </section>
  )
}

const ACTION_LABEL: Record<string, string> = {
  'backup.run': 'Backed up',
  'signups.change': 'Changed sign-ups',
  'invite.create': 'Made an invite',
  'invite.revoke': 'Revoked an invite',
  'user.delete': 'Deleted an account',
  'user.export': 'Exported an account',
  'role.change': 'Changed a role',
  'enchants.correct': 'Corrected enchant data',
}

function LogRow({ entry }: { entry: AdminLogEntry }) {
  return (
    <tr>
      <td>{new Date(entry.at).toLocaleString()}</td>
      <td>{entry.actor_account_id ?? <span className="muted">command line</span>}</td>
      <td>{ACTION_LABEL[entry.action] ?? entry.action}</td>
      <td>{entry.target_account_id ?? <span className="muted">—</span>}</td>
      <td>{entry.detail ?? ''}</td>
    </tr>
  )
}

/** What the admin area did (#238, ADR 0056): the record that a data request was handled. */
function ActionLog() {
  const log = useQuery({ queryKey: ['admin-log'], queryFn: api.adminLog })
  return (
    <section>
      <h2>Action log</h2>
      <p className="muted">
        Who did what, to which account, and when: account ids and actions only, never the data. Kept for a year, and
        kept after an account is deleted, as the record that its request was handled.
      </p>
      {log.isError && <p className="error">Couldn't load the log: {log.error.message}</p>}
      {log.data && log.data.length === 0 && <p className="muted">Nothing yet.</p>}
      {log.data && log.data.length > 0 && (
        <table className="admin-log">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">By</th>
              <th scope="col">What</th>
              <th scope="col">Account</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {log.data.map((entry) => (
              <LogRow key={entry.id} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/**
 * The admin area (#237, ADR 0055): every account, and what each role may do, for the admin
 * and superusers (`accounts.view`); only the admin changes roles (`roles.manage`). The
 * instance's shared data, health and backups too (#260), each behind its own permission.
 * Without users (ADR 0062) it's the one person's: those, and no accounts.
 */
export function Admin() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const users = me.data?.users ?? false
  const allowed = canAdmin(me.data)
  const accounts = users && can(me.data, 'accounts.view')
  const view = useQuery({ queryKey: ['admin-accounts'], queryFn: api.adminAccounts, enabled: accounts })
  return (
    <article className="admin">
      <p>
        <a href="#">← Back to the planner</a>
      </p>
      <h1>Admin</h1>
      {me.data && !allowed && <p className="muted">Only the admin and superusers can see this page.</p>}
      {view.isError && <p className="error">Couldn't load the accounts: {view.error.message}</p>}
      {view.data && (
        <>
          <Accounts
            view={view.data}
            canManage={can(me.data, 'roles.manage')}
            requests={{ canExport: can(me.data, 'users.export'), canDelete: can(me.data, 'users.delete') }}
          />
          <Roles view={view.data} />
        </>
      )}
      {users && can(me.data, 'signups.manage') && <Signups />}
      {allowed && <SharedData canRefresh={can(me.data, 'data.refresh')} canSignup={can(me.data, 'discord.signup')} />}
      {can(me.data, 'health.view') && <Health />}
      {can(me.data, 'backups.manage') && <Backups />}
      {users && can(me.data, 'log.view') && <ActionLog />}
    </article>
  )
}
