import { expect, test, type Page } from '@playwright/test'
import { DIALOGS, TABS, openDialog, openTab, serveApi, serveTab } from './support.ts'

/**
 * The shared type floor (#273, ADR 0064): no visible text under 14px, on any tab or dialog,
 * on a phone or a desktop. SVG text is measured as drawn, scaled by its viewBox.
 */
const FLOOR = 14

/** Each visible text under the floor: its size, element and a few words of it. */
function tooSmall(page: Page, within: string) {
  return page.evaluate(
    ([root, floor]) => {
      const found: string[] = []
      const scope = document.querySelector(root as string) ?? document.body
      const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        const text = walker.currentNode.textContent?.trim()
        const element = walker.currentNode.parentElement
        if (!text || !element || element.closest('.visually-hidden')) continue
        const box = element.getBoundingClientRect()
        const style = getComputedStyle(element)
        if (box.width === 0 || box.height === 0 || style.visibility === 'hidden') continue
        let size = parseFloat(style.fontSize)
        const svg = element.closest('svg')
        if (svg && svg.viewBox.baseVal.width > 0) {
          size *= svg.getBoundingClientRect().width / svg.viewBox.baseVal.width
        }
        if (size < (floor as number) - 0.05) {
          found.push(`${size.toFixed(1)}px <${element.tagName.toLowerCase()} class="${element.getAttribute('class') ?? ''}"> ${text.slice(0, 40)}`)
        }
      }
      return found
    },
    [within, FLOOR] as const,
  )
}

for (const [size, width, height, phone] of [
  ['phone', 375, 667, true],
  ['desktop', 1280, 800, false],
] as const) {
  test.describe(size, () => {
    test.use({ viewport: { width, height }, hasTouch: phone, isMobile: phone })

    for (const tab of TABS) {
      test(`${tab}: no text under ${FLOOR}px`, async ({ page }) => {
        await serveTab(page, tab)
        await openTab(page, tab)
        expect(await tooSmall(page, 'body')).toEqual([])
      })
    }

    for (const [tab, opener] of DIALOGS) {
      test(`${opener.source.replace(/[\^$]/g, '')} dialog: no text under ${FLOOR}px`, async ({ page }) => {
        await serveApi(page)
        await openDialog(page, tab, opener)
        expect(await tooSmall(page, 'dialog[open]')).toEqual([])
      })
    }
  })
}
