import { expect, test, type Page } from '@playwright/test'
import { TABS, openTab as open, serveApi, serveTab } from './support.ts'

/**
 * Phone screens (#153): no sideways scroll in portrait on any tab, and in landscape the
 * chrome leaves the content in view. The API answers from real responses recorded on a
 * copy of the database (e2e/api-fixtures.json).
 */

/**
 * How far the page reaches past the screen's right edge, in pixels. Measured against the
 * visual viewport: when content is too wide a phone zooms the page out, and innerWidth grows
 * with it, hiding the overflow.
 */
const overflow = (page: Page) =>
  page.evaluate(
    () => document.documentElement.scrollWidth - Math.round(window.visualViewport?.width ?? window.innerWidth),
  )

for (const [width, height] of [
  [375, 812],
  [412, 915],
]) {
  test.describe(`portrait ${width}x${height}`, () => {
    test.use({ viewport: { width, height }, hasTouch: true, isMobile: true })

    for (const tab of TABS) {
      test(`${tab}: nothing wider than the screen`, async ({ page }) => {
        await serveTab(page, tab)
        await open(page, tab)
        expect(await overflow(page)).toBeLessThanOrEqual(0)
      })
    }

    test('the gear table keeps its labels when rows stack', async ({ page }) => {
      await serveApi(page)
      await open(page, 'plan')
      const targets = page.getByRole('region', { name: 'Current gear targets' })
      const firstCell = targets.locator('[data-label="Target now"]').first()
      await expect(firstCell).toHaveCSS('display', 'block')
      expect(await firstCell.evaluate((cell) => getComputedStyle(cell, '::before').content)).toBe('"Target now"')
    })

    test('the status bar shows its links without a menu (#260)', async ({ page }) => {
      await serveApi(page)
      await open(page, 'upgrades')
      await expect(page.getByRole('link', { name: 'My account' })).toBeInViewport()
      await expect(page.getByRole('link', { name: 'Admin' })).toBeInViewport()
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
  [667, 375],
  [812, 375],
  [915, 412],
]) {
  test.describe(`landscape ${width}x${height}`, () => {
    test.use({ viewport: { width, height }, hasTouch: true, isMobile: true })

    // A sideways phone is wider than the portrait rules' 640px: on rc.4 the Plan tab's gear
    // table overflowed it and zoomed the whole page out.
    for (const tab of TABS) {
      test(`${tab}: nothing wider than the screen`, async ({ page }) => {
        await serveTab(page, tab)
        await open(page, tab)
        expect(await overflow(page)).toBeLessThanOrEqual(0)
      })
    }

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

test.describe('desktop zoom reflow', () => {
  // A 1440px desktop viewport at 200% zoom provides 720 CSS pixels of layout width.
  test.use({ viewport: { width: 720, height: 450 } })

  test('the Upgrades tabs fit at the reduced layout width', async ({ page }) => {
    await serveApi(page)
    await open(page, 'upgrades')
    const character = await page.getByRole('tab', { name: 'Character' }).boundingBox()
    expect(character).not.toBeNull()
    expect(character!.x).toBeGreaterThanOrEqual(0)
    expect(character!.x + character!.width).toBeLessThanOrEqual(720)
    expect(await overflow(page)).toBeLessThanOrEqual(0)
  })
})
