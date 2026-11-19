import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminLogEntry, AdminView, Me, SignupsAdmin } from '../api'
import { Admin } from './Admin'

const EVERY_PERMISSION = [
  'accounts.view',
  'backups.manage',
  'data.refresh',
  'discord.signup',
  'enchants.correct',
  'health.view',
  'log.view',
  'roles.manage',
  'signups.manage',
  'users.delete',
  'users.export',
]
const ADMIN: Me = {
  users: true,
  signed_in: true,
  admin: true,
  role: 'admin',
  permissions: EVERY_PERMISSION,
  signups_open: false,
}
const SUPERUSER: Me = { ...ADMIN, admin: false, role: 'superuser', permissions: ['accounts.view', 'data.refresh'] }
const USER: Me = { ...ADMIN, admin: false, role: 'user', permissions: [] }
/** Without users, everyone may do everything (ADR 0055); /api/me says so with users: false. */
const SOLO: Me = { users: false, signed_in: false, admin: true, role: null, permissions: [], signups_open: false }

const view: AdminView = {
  accounts: [
    {
      user_id: 1,
      account_id: 1001,
      role: 'admin',
      created_at: '2026-11-14T00:00:00Z',
      last_sign_in_at: '2026-11-19T00:00:00Z',
      characters: [{ id: 1, name: 'Brumboldt Doomlet', region: 'us', character_class: 'Warrior' }],
    },
    {
      user_id: 2,
      account_id: 2002,
      role: 'user',
      created_at: '2026-11-15T00:00:00Z',
      last_sign_in_at: '2026-11-18T00:00:00Z',
      characters: [],
    },
  ],
  roles: [
    { name: 'admin', permissions: EVERY_PERMISSION },
    { name: 'superuser', permissions: ['accounts.view'] },
    { name: 'user', permissions: [] },
  ],
  permissions: {
    'accounts.view': 'See every account, its role and its characters',
    'roles.manage': 'Make a user a superuser, or a user again',
  },
}

const log: AdminLogEntry[] = [
  {
    id: 2,
    at: '2026-11-19T12:00:00Z',
    actor_account_id: null,
    action: 'user.delete',
    target_account_id: 3003,
    detail: '12 rows, from the command line',
  },
  {
    id: 1,
    at: '2026-11-19T11:00:00Z',
    actor_account_id: 1001,
    action: 'role.change',
    target_account_id: 2002,
    detail: 'user -> superuser',
  },
]

const signups: SignupsAdmin = {
  signups: { open: false, source: 'setting', changed_at: null },
  setting: false,
  invites: [
    {
      id: 1,
      created_at: '2026-11-18T00:00:00Z',
      expires_at: '2026-11-25T00:00:00Z',
      created_by_account_id: 1001,
      used_at: null,
      used_by_account_id: null,
      revoked_at: null,
      state: 'open',
    },
    {
      id: 0,
      created_at: '2026-11-10T00:00:00Z',
      expires_at: '2026-11-17T00:00:00Z',
      created_by_account_id: 1001,
      used_at: '2026-11-11T00:00:00Z',
      used_by_account_id: 2002,
      revoked_at: null,
      state: 'used',
    },
  ],
}

const failed = {
  at: '2026-11-21T03:00:00Z',
  ok: false,
  key: null,
  size: null,
  rows: null,
  error: 'ClientError: NoSuchBucket',
  kept: null,
}
const health = {
  ready: true,
  database: { reachable: true, migrated: false },
  queue: { configured: false, reachable: false, queued: 0, started: 0, failed: 0, workers: 0, last_heartbeat: null },
  failures: [{ job: 'refresh pool', at: '2026-11-21T02:00:00Z', error: 'Forever Companion refused the request' }],
  budgets: [{ upstream: 'forevercompanion', window_seconds: 60, used: 100, limit: 100, waiting: true }],
  refreshes: [
    { name: 'Item pool', last: '2026-11-21T01:00:00Z' },
    { name: 'Enchants', last: null },
  ],
  leases: [{ name: 'pool', expires_at: '2026-11-21T05:00:00Z' }],
}
const backups = { configured: true, every_hours: 24, keep: 14, bucket: 'planner-backups', last: failed }

/** The Accounts section, once it has loaded: the log names the same accounts. */
async function accounts() {
  await screen.findByRole('heading', { name: 'Accounts' })
  return within(screen.getByRole('heading', { name: 'Accounts' }).closest('section')!)
}

function show(me: Me, routes: Record<string, () => Response> = {}) {
  const puts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const route = routes[`${init?.method ?? 'GET'} ${url}`]
      if (route) return route()
      if (url === '/api/me') return Response.json(me)
      if (url === '/api/discord') return Response.json({ available: false, signup_message: false })
      if (url === '/api/admin/log') return Response.json(log)
      if (url === '/api/admin/health') return Response.json(health)
      if (url === '/api/admin/backups' && init?.method === 'POST') {
        puts.push({ url, body: 'POST' })
        return Response.json({
          ...backups,
          last: { ...failed, ok: true, error: null, rows: 120, size: 48000, kept: 2 },
        })
      }
      if (url === '/api/admin/backups') return Response.json(backups)
      if (url === '/api/admin/invites' && init?.method === 'POST') {
        puts.push({ url, body: 'POST' })
        return Response.json({ invite: signups.invites[0], token: 'a-token-of-thirty-two-characters' })
      }
      if (url === '/api/admin/signups' && !init?.method) return Response.json(signups)
      if (url === '/api/admin/signups') {
        puts.push({ url, body: JSON.parse(String(init!.body)) as unknown })
        return Response.json({ ...signups, signups: { open: true, source: 'app', changed_at: '2026-11-20T00:00:00Z' } })
      }
      if (init?.method === 'DELETE') {
        puts.push({ url, body: 'DELETE' })
        return Response.json({ removed: { user: 1 } })
      }
      if (init?.method === 'PUT') {
        const body: unknown = JSON.parse(String(init.body))
        puts.push({ url, body })
        return Response.json({ ...view.accounts[1], role: 'superuser' })
      }
      return Response.json(view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Admin />
    </QueryClientProvider>,
  )
  return puts
}

describe('Admin', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("lists the accounts, and lets the admin make a user a superuser, never changing the admin's role", async () => {
    const puts = show(ADMIN)
    const row = (await accounts()).getByText('2002').closest('tr')!
    expect(within(row).getByText('none')).toBeTruthy()
    const admin = (await accounts()).getByText('1001').closest('tr')!
    expect(within(admin).getByText('Brumboldt Doomlet (US)')).toBeTruthy()
    expect(within(admin).queryByRole('combobox')).toBeNull()
    expect(within(admin).getByText('Admin')).toBeTruthy()

    fireEvent.change(screen.getByRole('combobox', { name: 'Role of account 2002' }), {
      target: { value: 'superuser' },
    })
    await waitFor(() => expect(puts).toEqual([{ url: '/api/admin/users/2/role', body: { role: 'superuser' } }]))
  })

  it('shows what each role may do', async () => {
    show(ADMIN)
    expect(await screen.findByRole('heading', { name: 'Roles' })).toBeTruthy()
    expect(screen.getAllByText('Make a user a superuser, or a user again')).toHaveLength(1)
    expect(screen.getByText('Their own characters and settings only.')).toBeTruthy()
  })

  it('shows a superuser the accounts, with no role changes', async () => {
    show(SUPERUSER)
    expect(await screen.findByText('2002')).toBeTruthy()
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('exports an account, and deletes it only once its id is typed in', async () => {
    const requests = show(ADMIN)
    const row = (await accounts()).getByText('2002').closest('tr')!
    expect(within(row).getByRole('link', { name: 'Export' }).getAttribute('href')).toBe('/api/admin/users/2/export')
    // The admin's own account can't be deleted from here.
    const admin = (await accounts()).getByText('1001').closest('tr')!
    expect(within(admin).queryByRole('button', { name: 'Delete…' })).toBeNull()

    fireEvent.click(within(row).getByRole('button', { name: 'Delete…' }))
    const confirm = within(row).getByRole('button', { name: 'Delete for good' }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(within(row).getByRole('textbox', { name: 'Type 2002 to confirm' }), { target: { value: '2001' } })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(within(row).getByRole('textbox', { name: 'Type 2002 to confirm' }), { target: { value: '2002' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(requests).toEqual([{ url: '/api/admin/users/2?confirm=2002', body: 'DELETE' }]))
  })

  it('shows the action log, newest first, with the command line named', async () => {
    show(ADMIN)
    const heading = await screen.findByRole('heading', { name: 'Action log' })
    const table = await within(heading.closest('section')!).findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining('command lineDeleted an account300312 rows, from the command line'),
      expect.stringContaining('1001Changed a role2002user -> superuser'),
    ])
  })

  it('gives a superuser no data requests and no log', async () => {
    show(SUPERUSER)
    expect(await screen.findByText('2002')).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Export' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Action log' })).toBeNull()
  })

  it('opens sign-ups, says where the setting comes from, and makes a one-time invite link', async () => {
    const requests = show(ADMIN)
    const section = (await screen.findByRole('heading', { name: 'Sign-ups' })).closest('section')!
    expect(section.textContent).toContain('from PLANNER_SIGNUPS (off)')
    expect(within(section).getByText(/by account 2002/)).toBeTruthy()

    fireEvent.click(within(section).getByRole('button', { name: 'Open sign-ups' }))
    await waitFor(() => expect(requests).toContainEqual({ url: '/api/admin/signups', body: { open: true } }))

    fireEvent.click(within(section).getByRole('button', { name: 'Make an invite link' }))
    const link = (await within(section).findByRole('textbox', { name: 'Invite link' })) as HTMLInputElement
    expect(link.value).toBe(`${window.location.origin}/#invite=a-token-of-thirty-two-characters`)
    expect(within(section).getByRole('button', { name: /Revoke the invite made/ })).toBeTruthy()
  })

  it('shows a failed backup, and backs up now (#240)', async () => {
    const requests = show(ADMIN)
    const section = (await screen.findByRole('heading', { name: 'Backups' })).closest('section')!
    expect(within(section).getByRole('alert').textContent).toContain('ClientError: NoSuchBucket')
    expect(section.textContent).toContain('Every 24 hours to planner-backups, encrypted; the newest 14 kept.')
    fireEvent.click(within(section).getByRole('button', { name: 'Back up now' }))
    expect(await within(section).findByText(/120 rows, 48 kB, 2 kept/)).toBeTruthy()
    expect(requests).toContainEqual({ url: '/api/admin/backups', body: 'POST' })
  })

  it('shows the instance health (#241)', async () => {
    show(ADMIN)
    const section = (await screen.findByRole('heading', { name: 'Instance health' })).closest('section')!
    expect(section.textContent).toContain('reachable, but not at the newest migration')
    expect(section.textContent).toContain('not set up (REDIS_URL)')
    expect(section.textContent).toContain('100 of 100 used (full: calls are waiting for room)')
    expect(section.textContent).toContain('Enchants: last refreshed never')
    expect(section.textContent).toContain('Running now: pool.')
    expect(section.textContent).toContain('refresh pool')
    expect(section.textContent).toContain('Forever Companion refused the request')
  })

  it('shows a user nothing', async () => {
    show(USER)
    expect(await screen.findByText('Only the admin and superusers can see this page.')).toBeTruthy()
    expect(screen.queryByText('2002')).toBeNull()
  })

  it('refreshes the shared data, saying when one is queued or cooling down (#260, #17)', async () => {
    show(ADMIN, {
      'POST /api/pool/refresh': () => Response.json({ state: 'queued', result: null, error: null }, { status: 202 }),
      'POST /api/enchants/refresh': () =>
        Response.json({ detail: 'Refreshed recently: again in about 7 minutes' }, { status: 429 }),
    })
    const section = within((await screen.findByRole('heading', { name: 'Shared data' })).closest('section')!)
    fireEvent.click(section.getByRole('button', { name: 'Refresh item pool' }))
    expect(await section.findByText('Queued: it runs in the background.')).toBeTruthy()
    fireEvent.click(section.getByRole('button', { name: 'Refresh enchant data' }))
    const note = await section.findByText('Refreshed recently: again in about 7 minutes')
    expect(note.className).toBe('muted')
    expect(section.queryByText(/failed/)).toBeNull()
  })

  it('updates the pinned Discord sign-up message, when the instance has one (#192)', async () => {
    const requests = show(ADMIN, {
      'GET /api/discord': () => Response.json({ available: false, signup_message: true }),
      'POST /api/discord/signup-message': () =>
        Response.json({ ok: false, action: 'none', message_id: null, error: 'give it Pin Messages' }),
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Update the Discord sign-up message' }))
    expect(await screen.findByText("The sign-up message wasn't updated: give it Pin Messages")).toBeTruthy()
    expect(requests).toEqual([])
  })

  it('offers no sign-up message without the setting', async () => {
    show(ADMIN)
    await screen.findByRole('heading', { name: 'Shared data' })
    expect(screen.queryByRole('button', { name: 'Update the Discord sign-up message' })).toBeNull()
  })

  it('shows the one person their shared data, health and backups without users, and no accounts (#260)', async () => {
    show(SOLO)
    expect(await screen.findByRole('heading', { name: 'Shared data' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'Instance health' })).toBeTruthy()
    expect(await screen.findByRole('heading', { name: 'Backups' })).toBeTruthy()
    for (const name of ['Accounts', 'Roles', 'Sign-ups', 'Action log']) {
      expect(screen.queryByRole('heading', { name })).toBeNull()
    }
    expect(screen.queryByText('Only the admin and superusers can see this page.')).toBeNull()
  })
})
