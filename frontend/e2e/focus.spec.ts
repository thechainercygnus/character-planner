// Each keypress depends on the focus left by the previous one.
/* eslint-disable no-await-in-loop */
import { expect, test } from '@playwright/test'
import { openTab, serveApi } from './support.ts'

for (const view of ['guest', 'upgrades']) {
  test(`keyboard focus is visible on the ${view} page`, async ({ page }) => {
    await serveApi(page)
    await openTab(page, view)
    const firstLink = page.getByRole('link', { name: 'DL Durish Labs home' })
    await page.keyboard.press('Tab')
    await expect(firstLink).toBeFocused()
    for (let stop = 0; stop < 12; stop += 1) {
      const focused = page.locator(':focus')
      await expect(focused).toHaveCSS('outline-style', 'solid')
      await expect(focused).toHaveCSS('outline-width', '2px')
      await expect(focused).toHaveCSS('outline-color', 'rgb(214, 239, 141)')
      await expect(focused).toHaveCSS('outline-offset', '3px')
      await page.keyboard.press('Tab')
      if (await page.evaluate(() => document.activeElement === document.body)) break
    }
  })
}
