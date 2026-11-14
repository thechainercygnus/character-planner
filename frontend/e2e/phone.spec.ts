import { expect, test, type Page } from '@playwright/test'
import fixtures from './api-fixtures.json' with { type: 'json' }

/**
 * Phone screens (#153): no sideways scroll in portrait on any tab, and in landscape the
 * chrome leaves the content in view. The API answers from real responses recorded on a
 * copy of the database (e2e/api-fixtures.json).
 */

const answers = fixtures as Record<string, { status: number; body: unknown }>
const TABS = ['upgrades', 'dungeons', 'plan', 'talents', 'progress', 'character', 'privacy', 'guest']

async function serveApi(page: Page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    // Guest mode's recommendations have the same shape as the character's.
    const known = path === '/api/guest/recommendations' ? '/api/recommendations' : path
    const answer = answers[known] ?? { status: 200, body: [] }
    return route.fulfill({ status: answer.status, json: answer.body })
  })
}

/** Open a tab and wait until the layout has settled: data in, fonts loaded. */
async function open(page: Page, hash: string) {
  await page.goto(`/#${hash}`)
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main :is(h1, h2, section):visible').first()).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
}

/** How far the page reaches past the screen's right edge, in pixels. */
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)

for (const [width, height] of [
  [375, 812],
  [412, 915],
]) {
  test.describe(`portrait ${width}x${height}`, () => {
    test.use({ viewport: { width, height }, hasTouch: true, isMobile: true })

    for (const tab of TABS) {
      test(`${tab}: nothing wider than the screen`, async ({ page }) => {
        await serveApi(page)
        await open(page, tab)
        expect(await overflow(page)).toBeLessThanOrEqual(0)
      })
    }

    test('the open menu stays on screen', async ({ page }) => {
      await serveApi(page)
      await open(page, 'upgrades')
      await page.getByTitle('More actions').click()
      await expect(page.getByRole('button', { name: 'Refresh item pool' })).toBeVisible()
      expect(await overflow(page)).toBeLessThanOrEqual(0)
    })

    test('a tab off to the side scrolls into view when chosen', async ({ page }) => {
      await serveApi(page)
      await open(page, 'upgrades')
      const character = page.getByRole('tab', { name: 'Character' })
      await character.click()
      await expect(character).toBeInViewport()
    })
  })
}

for (const [width, height] of [
  [812, 375],
  [915, 412],
]) {
  test.describe(`landscape ${width}x${height}`, () => {
    test.use({ viewport: { width, height }, hasTouch: true, isMobile: true })

    test('content starts within the top third', async ({ page }) => {
      await serveApi(page)
      await open(page, 'upgrades')
      const tabs = await page.getByRole('tablist').boundingBox()
      expect(tabs).not.toBeNull()
      expect(tabs!.y + tabs!.height).toBeLessThanOrEqual(height * 0.34)
      expect(await overflow(page)).toBeLessThanOrEqual(0)
    })
  })
}

test.describe('desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('the layout is the desktop one: header detail shown, no touch sizes', async ({ page }) => {
    await serveApi(page)
    await open(page, 'upgrades')
    await expect(page.getByText(/^Level 19 /)).toBeVisible()
    const sync = await page.getByRole('button', { name: 'Sync now' }).boundingBox()
    expect(sync!.height).toBeLessThan(44)
  })
})
