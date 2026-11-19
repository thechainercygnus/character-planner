import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, can, type Account, type AdminView } from '../api'

const ROLE_LABEL: Record<string, string> = { admin: 'Admin', superuser: 'Superuser', user: 'User' }

function day(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString()
}

/** The admin makes a user a superuser, or a user again; the admin's own role never changes. */
function RoleCell({ account, canManage }: { account: Account; canManage: boolean }) {
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: api.setRole,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-accounts'] }),
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

function Accounts({ view, canManage }: { view: AdminView; canManage: boolean }) {
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
          <Accounts view={view.data} canManage={can(me.data, 'roles.manage')} />
          <Roles view={view.data} />
        </>
      )}
    </article>
  )
}
