import type { Page, Request } from '@playwright/test'
import fixtures from './api-fixtures.json' with { type: 'json' }

/**
 * The mocked API every browser check runs against: recorded real responses
 * (api-fixtures.json), plus answers a test sets for the routes it exercises.
 */
const recorded = fixtures as Record<string, { status: number; body: unknown }>

export type Answer = { status?: number; body: unknown }
/** "GET /api/choices" (or "/api/choices", any method) -> the answer, or a function of the request. */
export type Answers = Record<string, Answer | ((request: Request) => Answer)>

/** Serve the API; returns every request the page sent, to check what the app asked for. */
export async function serveApi(page: Page, answers: Answers = {}): Promise<Request[]> {
  const sent: Request[] = []
  await page.route('**/api/**', (route) => {
    const request = route.request()
    sent.push(request)
    const path = new URL(request.url()).pathname
    const given = answers[`${request.method()} ${path}`] ?? answers[path]
    const answer = typeof given === 'function' ? given(request) : given
    // Guest mode's recommendations have the same shape as the character's.
    const known = path === '/api/guest/recommendations' ? '/api/recommendations' : path
    const { status = 200, body } = answer ?? recorded[known] ?? { status: 200, body: [] }
    return route.fulfill({ status, json: body })
  })
  return sent
}

/** Open a tab and wait until the layout has settled: data in, fonts loaded. */
export async function openTab(page: Page, hash: string) {
  await page.goto(`/#${hash}`)
  await page.waitForLoadState('networkidle')
  await page.locator('main :is(h1, h2, section):visible').first().waitFor()
  await page.evaluate(() => document.fonts.ready)
}

export const TABS = [
  'upgrades',
  'dungeons',
  'plan',
  'talents',
  'professions',
  'progress',
  'character',
  'privacy',
  'guest',
  'admin',
  'account',
  'guild',
]

const EVERY_PERMISSION = [
  'accounts.view',
  'data.refresh',
  'discord.signup',
  'enchants.correct',
  'log.view',
  'roles.manage',
  'signups.manage',
  'users.delete',
  'users.export',
]

/** The admin signed in on an instance with users (#237): the admin page needs users on. */
const USERS_ON: Answers = {
  '/api/me': {
    body: {
      users: true,
      signed_in: true,
      admin: true,
      role: 'admin',
      permissions: EVERY_PERMISSION,
      signups_open: false,
    },
  },
  '/api/admin/signups': {
    body: {
      signups: { open: false, source: 'app', changed_at: '2026-11-19T00:00:00Z' },
      setting: true,
      invites: [
        {
          id: 2,
          created_at: '2026-11-19T00:00:00Z',
          expires_at: '2026-11-26T00:00:00Z',
          created_by_account_id: 1001,
          used_at: null,
          used_by_account_id: null,
          revoked_at: null,
          state: 'open',
        },
        {
          id: 1,
          created_at: '2026-11-12T00:00:00Z',
          expires_at: '2026-11-19T00:00:00Z',
          created_by_account_id: 1001,
          used_at: '2026-11-13T00:00:00Z',
          used_by_account_id: 2002,
          revoked_at: null,
          state: 'used',
        },
      ],
    },
  },
  '/api/admin/log': {
    body: [
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
    ],
  },
  '/api/admin/accounts': {
    body: {
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
          role: 'superuser',
          created_at: '2026-11-15T00:00:00Z',
          last_sign_in_at: '2026-11-18T00:00:00Z',
          characters: [],
        },
      ],
      roles: [
        { name: 'admin', permissions: EVERY_PERMISSION },
        { name: 'superuser', permissions: ['accounts.view', 'data.refresh', 'enchants.correct'] },
        { name: 'user', permissions: [] },
      ],
      permissions: {
        'accounts.view': 'See every account, its role and its characters',
        'roles.manage': 'Make a user a superuser, or a user again',
        'data.refresh': 'Refresh the shared game data: items, the item pool, enchants and talents',
        'enchants.correct': 'Correct the shared enchant data: material levels and crafted effects',
        'discord.signup': "Update the Discord bot's pinned sign-up message",
      },
    },
  },
}

const member = (id: number, name: string, role: string, level: number, yours: boolean, player: number | null) => ({
  character_id: id,
  name,
  character_class: 'Warrior',
  spec: role === 'tank' ? 'Protection' : 'Arms',
  role,
  level,
  yours,
  player,
})

/** The Guild tab (#18, #215): two guilds, your alt not in the view yet, and another player's two characters grouped. */
const GUILD: Answers = {
  '/api/guilds': {
    body: {
      guilds: [
        {
          region: 'us',
          guild_id: 670649,
          name: 'Daves Discount Meats',
          grouped: false,
          characters: [
            { id: 1, name: 'Brumboldt Doomlet', joined: true, role: 'tank' },
            { id: 2, name: 'Brumalt Doomlet', joined: false, role: null },
          ],
        },
        {
          region: 'us',
          guild_id: 111,
          name: 'Another Guild',
          grouped: false,
          characters: [{ id: 3, name: 'Elsewhere Doomlet', joined: false, role: null }],
        },
      ],
    },
  },
  '/api/guild': {
    body: {
      guild: { id: 670649, name: 'Daves Discount Meats' },
      opted_in: true,
      role: 'tank',
      members: [
        member(1, 'Brumboldt Doomlet', 'tank', 19, true, null),
        member(7, 'Hollie Light', 'dps', 20, false, 1),
        member(8, 'Hollie Alt', 'dps', 14, false, 1),
      ],
      going: [1, 7],
      roles: { tank: 1, healer: 0, dps: 1 },
      missing_roles: ['healer'],
      dungeons: [],
      channel: null,
      shared_alerts: [],
      alerts: [],
    },
  },
}

/** Serve the API as a tab needs it: the admin page and the Guild tab with users on, the rest as recorded. */
export function serveTab(page: Page, tab: string): Promise<Request[]> {
  if (tab === 'guild') return serveApi(page, { ...USERS_ON, ...GUILD })
  return serveApi(page, tab === 'admin' ? USERS_ON : {})
}

/** Every dialog: [the tab it opens from, its opening button]. */
export const DIALOGS: [string, RegExp][] = [
  ['upgrades', /^Upgrades settings/],
  ['upgrades', /^Stat weights/],
  ['plan', /^Edit targets/],
  ['talents', /^Edit plan$/],
  ['upgrades', /^Alerts$/],
  ['upgrades', /^Discord$/],
  ['character', /^Import again$/],
]

/** Open a dialog from its tab; on a phone its button may be in the More actions menu. */
export async function openDialog(page: Page, tab: string, opener: RegExp) {
  await openTab(page, tab)
  let button = page.getByRole('button', { name: opener }).first()
  if (!(await button.isVisible())) {
    await page.getByTitle('More actions').click()
    button = page.getByRole('button', { name: opener }).first()
  }
  await button.click()
  const dialog = page.locator('dialog[open]')
  await dialog.waitFor()
  return dialog
}
