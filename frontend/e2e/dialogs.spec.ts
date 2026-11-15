import { expect, test, type Locator, type Page } from '@playwright/test'
import fixtures from './api-fixtures.json' with { type: 'json' }

/**
 * Every dialog fits the screen it opens on, phone or desktop, and closes again. On rc.4
 * the Upgrades settings and Discord dialogs opened with their tops above a phone's screen.
 */

const answers = fixtures as Record<string, { status: number; body: unknown }>

async function serveApi(page: Page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const answer = answers[path] ?? { status: 200, body: [] }
    return route.fulfill({ status: answer.status, json: answer.body })
  })
}

// [tab, the button that opens it]
const DIALOGS: [string, RegExp][] = [
  ['upgrades', /^Upgrades settings/],
  ['upgrades', /^Stat weights/],
  ['plan', /^Edit targets/],
  ['talents', /^Edit plan$/],
  ['upgrades', /^Alerts$/],
  ['upgrades', /^Discord$/],
]

const SIZES: [string, number, number, boolean][] = [
  ['phone portrait', 375, 667, true],
  ['phone landscape', 667, 375, true],
  ['desktop', 1280, 800, false],
]

/** The dialog's box, and the visible part of the screen. */
async function fits(page: Page, dialog: Locator) {
  const box = await dialog.boundingBox()
  const screen = await page.evaluate(() => {
    const visual = window.visualViewport
    return { width: visual?.width ?? window.innerWidth, height: visual?.height ?? window.innerHeight }
  })
  expect(box).not.toBeNull()
  expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height).toBeLessThanOrEqual(screen.height + 0.5)
  expect(box!.x + box!.width).toBeLessThanOrEqual(screen.width + 0.5)
}

for (const [size, width, height, phone] of SIZES) {
  test.describe(size, () => {
    test.use({ viewport: { width, height }, hasTouch: phone, isMobile: phone })

    for (const [tab, opener] of DIALOGS) {
      test(`${opener.source.replace(/[\^$]/g, '')} fits and closes`, async ({ page }) => {
        await serveApi(page)
        await page.goto(`/#${tab}`)
        await page.waitForLoadState('networkidle')
        // On a phone the status bar's buttons may sit in the More actions menu.
        let button = page.getByRole('button', { name: opener }).first()
        if (!(await button.isVisible())) {
          await page.getByTitle('More actions').click()
          button = page.getByRole('button', { name: opener }).first()
        }
        await button.click()
        const dialog = page.locator('dialog[open]')
        await expect(dialog).toBeVisible()
        await page.evaluate(() => document.fonts.ready)
        await fits(page, dialog)
        // The close button is on screen: the way out is never scrolled away.
        const close = dialog.getByRole('button', { name: 'Close' }).first()
        await expect(close).toBeInViewport()
        await close.click()
        await expect(page.locator('dialog[open]')).toHaveCount(0)
      })
    }
  })
}
