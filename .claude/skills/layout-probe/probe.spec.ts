// A throwaway layout probe for the layout-probe skill. Copy it to frontend/e2e/probe.spec.ts,
// edit SIZES, TAB and the step in `inspect`, run it with
//   npx playwright test e2e/probe.spec.ts --reporter=line 2>&1 | grep -E "^P |Error"
// and delete it afterwards. Never commit it: findings become checks in phone.spec.ts or
// dialogs.spec.ts.
import { test, type Page } from '@playwright/test'
import fixtures from './api-fixtures.json' with { type: 'json' }

const answers = fixtures as Record<string, { status: number; body: unknown }>
const SIZES: [number, number][] = [
  [375, 667],
  [667, 375],
]
const TAB = 'plan'
const SHOTS = '' // a folder (the scratchpad) to save screenshots in; empty for none

async function serveApi(page: Page) {
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const known = path === '/api/guest/recommendations' ? '/api/recommendations' : path
    const answer = answers[known] ?? { status: 200, body: [] }
    return route.fulfill({ status: answer.status, json: answer.body })
  })
}

/** What to look at; prints one "P ..." line. */
async function inspect(page: Page, label: string) {
  // Optional: widen text the way CI's Linux fonts do, to see what breaks first.
  // await page.addStyleTag({ content: 'body { letter-spacing: 1px }' })

  // Optional: open a dialog first.
  // await page.getByRole('button', { name: /^Upgrades settings/ }).first().click()

  const report = await page.evaluate(() => {
    const screen = Math.round(window.visualViewport?.width ?? window.innerWidth)
    // Inside a scrolling or clipping box, being wide is fine: only unclipped boxes widen the page.
    const clipped = (element: Element) => {
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (getComputedStyle(parent).overflowX !== 'visible') return true
      }
      return false
    }
    const wide = [...document.querySelectorAll('body *')]
      .filter((e) => e.getBoundingClientRect().right > screen + 1 && !clipped(e))
      .slice(0, 5)
      .map((e) => `${e.tagName}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`)
    const dialog = document.querySelector('dialog[open]')?.getBoundingClientRect()
    return {
      // innerWidth/innerHeight grow when a phone zooms an overflowing page out; visualViewport doesn't.
      inner: [window.innerWidth, window.innerHeight],
      visual: [screen, Math.round(window.visualViewport?.height ?? window.innerHeight)],
      overflow: document.documentElement.scrollWidth - screen,
      wide,
      dialog: dialog && { top: Math.round(dialog.top), bottom: Math.round(dialog.bottom) },
    }
  })
  console.log(`P ${label} ${JSON.stringify(report)}`)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${label}.png` })
}

for (const [width, height] of SIZES) {
  test(`probe ${width}x${height}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: true })
    const page = await context.newPage()
    await serveApi(page)
    await page.goto(`/#${TAB}`)
    await page.waitForLoadState('networkidle')
    await page.evaluate(() => document.fonts.ready)
    await inspect(page, `${TAB}-${width}x${height}`)
  })
}
