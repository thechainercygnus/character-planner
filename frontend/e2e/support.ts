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

export const TABS = ['upgrades', 'dungeons', 'plan', 'talents', 'professions', 'progress', 'character', 'privacy', 'guest']

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
