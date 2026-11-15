import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { DIALOGS, TABS, openDialog, openTab, serveApi } from './support.ts'

/**
 * Accessibility (#165): axe finds nothing on any tab or dialog, on a phone or a desktop.
 * Every finding fails, not only serious ones: they were all fixed, so keep it that way.
 * A rule that's wrong for this app is turned off here with a comment, never silently.
 */

type Violation = { id: string; impact?: string | null; help: string; nodes: { target: unknown }[] }

/** One line per finding, so a failure says what and where. */
const describe = (violations: Violation[]) =>
  violations.map((v) => `${v.impact} ${v.id}: ${v.help} (${JSON.stringify(v.nodes.map((n) => n.target))})`)

for (const [size, width, height, phone] of [
  ['phone', 375, 667, true],
  ['desktop', 1280, 800, false],
] as const) {
  test.describe(size, () => {
    test.use({ viewport: { width, height }, hasTouch: phone, isMobile: phone })

    for (const tab of TABS) {
      test(`${tab} tab`, async ({ page }) => {
        await serveApi(page)
        await openTab(page, tab)
        const { violations } = await new AxeBuilder({ page }).analyze()
        expect(describe(violations)).toEqual([])
      })
    }

    for (const [tab, opener] of DIALOGS) {
      test(`${opener.source.replace(/[\^$]/g, '')} dialog`, async ({ page }) => {
        await serveApi(page)
        await openDialog(page, tab, opener)
        const { violations } = await new AxeBuilder({ page }).include('dialog[open]').analyze()
        expect(describe(violations)).toEqual([])
      })
    }
  })
}
