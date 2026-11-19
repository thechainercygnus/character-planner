import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, can, type Account, type AdminLogEntry, type AdminView } from '../api'

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

const ACTION_LABEL: Record<string, string> = {
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
 * The admin area (#237, ADR 0055): every account, and what each role may do. For the admin
 * and superusers (`accounts.view`); only the admin changes roles (`roles.manage`).
 */
export function Admin() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const allowed = can(me.data, 'accounts.view')
  const view = useQuery({ queryKey: ['admin-accounts'], queryFn: api.adminAccounts, enabled: allowed })
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
          {can(me.data, 'log.view') && <ActionLog />}
        </>
      )}
    </article>
  )
}
