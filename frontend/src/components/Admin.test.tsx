import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdminView, Me } from '../api'
import { Admin } from './Admin'

const EVERY_PERMISSION = ['accounts.view', 'data.refresh', 'discord.signup', 'enchants.correct', 'roles.manage']
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

function show(me: Me) {
  const puts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/me') return Response.json(me)
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
    const row = (await screen.findByText('2002')).closest('tr')!
    expect(within(row).getByText('none')).toBeTruthy()
    const admin = screen.getByText('1001').closest('tr')!
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

  it('shows a user nothing', async () => {
    show(USER)
    expect(await screen.findByText('Only the admin and superusers can see this page.')).toBeTruthy()
    expect(screen.queryByText('2002')).toBeNull()
  })
})
