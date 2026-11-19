import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GuildView, MyGuilds } from '../api'
import { Guild } from './Guild'

const GUILD = { id: 670649, name: 'Daves Discount Meats' }

const joined: GuildView = {
  guild: GUILD,
  opted_in: true,
  role: null,
  members: [
    {
      character_id: 1,
      name: 'Brum Doomlet',
      character_class: 'Warrior',
      spec: 'Protection',
      role: 'tank',
      level: 19,
      yours: true,
      player: null,
    },
    {
      character_id: 3,
      name: 'Fizz Bang',
      character_class: 'Mage',
      spec: 'Fire',
      role: 'dps',
      level: 31,
      yours: false,
      player: null,
    },
  ],
  going: [1, 3],
  roles: { tank: 1, healer: 0, dps: 1 },
  missing_roles: ['healer'],
  dungeons: [
    {
      dungeon_id: 'deadmines',
      dungeon: 'The Deadmines',
      min_level: 17,
      max_level: 26,
      total_gain: 11.5,
      in_range: [1],
      needs: {
        '1': [
          {
            item: 'Cape of the Brotherhood',
            item_id: 5193,
            slot: 'BACK',
            score_gain: 6,
            wowhead: 'https://www.wowhead.com/forever/item=5193',
          },
        ],
      },
    },
  ],
}

type Call = { url: string; method: string; body: unknown; as: string | null }

function serve(view: GuildView, mine: MyGuilds = { guilds: [] }) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : null,
        as: headers['X-Character-Id'] ?? null,
      })
      if (url.startsWith('/api/guilds')) return Response.json(mine)
      if (url === '/api/notifications') {
        return Response.json({
          destinations: [],
          alerts: [{ kind: 'level_up', audience: 'user', label: 'Level-ups' }],
          recent: [],
          system_alerts_to_user: false,
        })
      }
      return Response.json(view)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Guild />
    </QueryClientProvider>,
  )
  return calls
}

describe('Guild', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says so when the character has no guild', async () => {
    serve({ ...joined, guild: null, opted_in: false, members: [], dungeons: [] })
    expect(await screen.findByText(/isn't in a guild/)).toBeTruthy()
  })

  it('offers to join, with a role, and shows nobody until then', async () => {
    const calls = serve({ ...joined, opted_in: false, members: [], going: [], dungeons: [], missing_roles: [] })
    expect(await screen.findByRole('heading', { name: 'Daves Discount Meats' })).toBeTruthy()
    expect(screen.queryByText('Fizz Bang')).toBeNull()
    fireEvent.change(screen.getByRole('combobox', { name: 'Your role' }), { target: { value: 'healer' } })
    fireEvent.click(screen.getByRole('button', { name: 'Join the guild view' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')).toMatchObject({
      url: '/api/guild/membership',
      method: 'PUT',
      body: { opted_in: true, role: 'healer' },
    })
  })

  it('shows the members, a missing role and the best runs', async () => {
    serve(joined)
    expect(await screen.findByText('Fizz Bang')).toBeTruthy()
    expect(screen.getByText('(yours)')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toBe('No healer among the members going.')
    expect(screen.getByText('The Deadmines')).toBeTruthy()
    expect(screen.getByText(/\+11\.5 · 1 of 2 in range/)).toBeTruthy()
    const cape = screen.getByRole('link', { name: 'Cape of the Brotherhood' })
    expect(cape.getAttribute('href')).toBe('https://www.wowhead.com/forever/item=5193')
    expect(cape.parentElement?.textContent).toBe('Cape of the Brotherhood (+6.0)')
  })

  it('asks again for just the members going', async () => {
    const calls = serve(joined)
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Fizz Bang is going' }))
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/guild?going=1'))
  })

  it('sets the guild channel and shares chosen alerts (#163)', async () => {
    const withAlerts: GuildView = {
      ...joined,
      shared_alerts: [],
      channel: null,
      alerts: [
        { kind: 'level_up', audience: 'user', label: 'Level-ups' },
        { kind: 'new_upgrade', audience: 'user', label: 'New upgrades worth having' },
      ],
    }
    const calls = serve(withAlerts)
    expect(await screen.findByText('No channel yet.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Channel webhook URL'), {
      target: { value: 'https://discord.com/api/webhooks/1/abc' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Set' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/guild/channel')).toMatchObject({
        url: '/api/guild/channel',
        method: 'PUT',
        body: { url: 'https://discord.com/api/webhooks/1/abc' },
      }),
    )
    fireEvent.click(screen.getByRole('checkbox', { name: 'Level-ups' }))
    await waitFor(() =>
      expect(calls.find((c) => c.url === '/api/guild/shared-alerts')?.body).toEqual({ alerts: ['level_up'] }),
    )
  })

  it('shows who set the channel, and its last error', async () => {
    serve({
      ...joined,
      shared_alerts: ['level_up'],
      alerts: [{ kind: 'level_up', audience: 'user', label: 'Level-ups' }],
      channel: {
        url: '…/webhooks/1/••••',
        set_by: 'Fizz Bang',
        set_at: '2026-11-15T10:00:00',
        last_sent_at: null,
        last_error: 'HTTP 404: the webhook may have been deleted',
      },
    })
    expect(await screen.findByText(/set by Fizz Bang/)).toBeTruthy()
    expect(screen.getByText(/Last error: HTTP 404/)).toBeTruthy()
    expect((screen.getByRole('checkbox', { name: 'Level-ups' }) as HTMLInputElement).checked).toBe(true)
    expect(screen.getByRole('button', { name: 'Replace' })).toBeTruthy()
  })

  it('leaves the guild view', async () => {
    const calls = serve(joined)
    fireEvent.click(await screen.findByRole('button', { name: 'Leave the guild view' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ opted_in: false, role: null }))
  })

  describe('your guilds (#215)', () => {
    const two: MyGuilds = {
      guilds: [
        {
          region: 'us',
          guild_id: 670649,
          name: 'Daves Discount Meats',
          grouped: false,
          characters: [
            { id: 1, name: 'Brum Doomlet', joined: true, role: 'tank' },
            { id: 4, name: 'Brum Alt', joined: false, role: null },
            { id: 5, name: 'Brum Third', joined: false, role: null },
          ],
        },
        {
          region: 'us',
          guild_id: 111,
          name: 'Other Guild',
          grouped: false,
          characters: [{ id: 6, name: 'Elsewhere', joined: false, role: null }],
        },
      ],
    }

    it('picks a guild, and sees it through one of your characters there', async () => {
      const calls = serve(joined, two)
      const other = await screen.findByRole('button', { name: 'Other Guild' })
      expect(screen.getByRole('button', { name: 'Daves Discount Meats' }).getAttribute('aria-pressed')).toBe('true')
      await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ url: '/api/guild', as: '1' })))
      fireEvent.click(other)
      await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ url: '/api/guild', as: '6' })))
    })

    it('joins with several at once, sharing chosen alerts for each', async () => {
      const calls = serve(joined, two)
      expect(await screen.findByText('Your characters in Daves Discount Meats')).toBeTruthy()
      fireEvent.click(screen.getByRole('checkbox', { name: "Also share alerts with the guild's channel" }))
      fireEvent.click(await screen.findByRole('checkbox', { name: 'Level-ups' }))
      fireEvent.click(screen.getByRole('button', { name: 'Join with these 2' }))
      await waitFor(() =>
        expect(calls.find((c) => c.url === '/api/guilds/members')?.body).toEqual({
          region: 'us',
          guild_id: 670649,
          join: [4, 5],
          role: null,
          shared_alerts: ['level_up'],
        }),
      )
      fireEvent.click(screen.getByRole('button', { name: 'Leave the guild view with Brum Doomlet' }))
      await waitFor(() =>
        expect(calls.filter((c) => c.url === '/api/guilds/members').map((c) => c.body)).toContainEqual({
          region: 'us',
          guild_id: 670649,
          leave: [1],
        }),
      )
    })

    it('shows your characters as one player only when you choose to', async () => {
      const calls = serve(joined, two)
      fireEvent.click(await screen.findByRole('checkbox', { name: 'Show my characters here as one player' }))
      await waitFor(() =>
        expect(calls.find((c) => c.url === '/api/guilds/grouping')?.body).toEqual({
          region: 'us',
          guild_id: 670649,
          grouped: true,
        }),
      )
    })

    it("marks a grouped player's characters, and lets only one of them go", async () => {
      const grouped: GuildView = {
        ...joined,
        members: [
          { ...joined.members[0]!, player: 1 },
          { ...joined.members[0]!, character_id: 4, name: 'Brum Alt', level: 15, player: 1 },
          joined.members[1]!,
        ],
        going: [1, 3],
      }
      const calls = serve(grouped)
      expect(await screen.findAllByText('player 1')).toHaveLength(2)
      fireEvent.click(screen.getByRole('checkbox', { name: 'Brum Alt is going' }))
      await waitFor(() => expect(calls.map((c) => c.url)).toContain('/api/guild?going=3&going=4'))
    })
  })
})
