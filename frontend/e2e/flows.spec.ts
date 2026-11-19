import { expect, test } from '@playwright/test'
import { DIALOGS, TABS, openDialog, openTab, serveApi } from './support.ts'

/**
 * The main flows (#165), driven in the browser against the mocked API: switching tabs,
 * pinning and dismissing an upgrade, guest mode, and closing dialogs from the keyboard.
 * The fixtures' first upgrade slot is Neck: Tarnished Locket (a target) and Snake Eye
 * Kaleidoscope.
 */

const LOCKET = 279870
const KALEIDOSCOPE = 273088

// The tab bar's tabs; Privacy and guest mode open from links, not the bar.
for (const tab of TABS.filter((t) => !['privacy', 'guest', 'admin', 'account'].includes(t))) {
  test(`the ${tab} tab opens from the tab bar and from its address`, async ({ page }) => {
    await serveApi(page)
    await openTab(page, tab === 'upgrades' ? 'plan' : 'upgrades')
    const button = page.getByRole('tablist').getByRole('tab', { name: new RegExp(`^${tab}`, 'i') })
    await button.click()
    await expect(button).toHaveAttribute('aria-selected', 'true')
    await expect(page).toHaveURL(new RegExp(`#${tab}$`))
    // An address opens its tab directly, as a bookmark or a shared link would.
    await page.goto('about:blank')
    await openTab(page, tab)
    await expect(page.getByRole('tab', { selected: true })).toHaveText(new RegExp(`^${tab}`, 'i'))
  })
}

test('the details of an upgrade open and close', async ({ page }) => {
  await serveApi(page)
  await openTab(page, 'upgrades')
  const details = page.getByRole('button', { name: /^Show details for Neck/ })
  await details.click()
  await expect(page.getByRole('button', { name: /^Hide details for Neck/ })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('Snake Eye Kaleidoscope').first()).toBeVisible()
  await page.getByRole('button', { name: /^Hide details for Neck/ }).click()
  await expect(page.getByRole('button', { name: /^Show details for Neck/ })).toHaveAttribute('aria-expanded', 'false')
})

test('pinning an upgrade asks to make it the slot target', async ({ page }) => {
  const sent = await serveApi(page, { 'POST /api/targets/pins': { body: { targets: {} } } })
  await openTab(page, 'upgrades')
  await page.getByRole('button', { name: /^Show details for Neck/ }).click()
  await page.getByRole('button', { name: 'Make target' }).first().click()
  await expect
    .poll(() => sent.filter((r) => r.method() === 'POST').map((r) => r.postDataJSON()))
    .toEqual([{ item_id: KALEIDOSCOPE, slot: 'NECK' }])
})

test('a dismissed item leaves the suggestions and can be brought back', async ({ page }) => {
  let dismissed: { item_id: number; name: string; choice: string; created_at: string }[] = []
  const sent = await serveApi(page, {
    'GET /api/choices': () => ({ body: dismissed }),
    [`PUT /api/choices/${LOCKET}`]: (request) => {
      const { name, choice } = request.postDataJSON() as { name: string; choice: string }
      dismissed = [{ item_id: LOCKET, name, choice, created_at: '2026-11-15T00:00:00' }]
      return { body: dismissed }
    },
    [`DELETE /api/choices/${LOCKET}`]: () => {
      dismissed = []
      return { body: dismissed }
    },
  })
  await openTab(page, 'upgrades')
  await page.getByRole('button', { name: /^Show details for Neck/ }).click()
  await page.getByRole('button', { name: 'Never suggest' }).first().click()

  const hidden = page.getByRole('heading', { name: 'Never suggested' })
  await expect(hidden).toBeVisible()
  await expect(page.locator('.dismissed')).toContainText('Tarnished Locket')
  await page.locator('.dismissed').getByRole('button').first().click()
  await expect(hidden).toHaveCount(0)
  expect(sent.filter((r) => r.url().includes(`/api/choices/${LOCKET}`)).map((r) => r.method())).toEqual([
    'PUT',
    'DELETE',
  ])
})

test('guest mode asks for the class, level and faction picked', async ({ page }) => {
  const sent = await serveApi(page)
  await openTab(page, 'guest')
  await page.getByRole('combobox', { name: /^Class/ }).selectOption('mage')
  await page.getByLabel('Level', { exact: true }).fill('24')
  await page.getByRole('combobox', { name: /^Faction/ }).selectOption('horde')
  await expect
    .poll(() =>
      sent
        .map((r) => new URL(r.url()))
        .filter((url) => url.pathname === '/api/guest/recommendations')
        .map((url) => Object.fromEntries(url.searchParams))
        .at(-1),
    )
    .toMatchObject({ class: 'mage', level: '24', faction: 'horde' })
  await expect(page.locator('.guest-mode table').first()).toBeVisible()

  await page.getByLabel('Level', { exact: true }).fill('0')
  await expect(page.getByText('Level must be a whole number from 1 to 80.')).toBeVisible()
})

for (const [tab, opener] of DIALOGS) {
  test(`${opener.source.replace(/[\^$]/g, '')} closes with Escape and gives focus back`, async ({ page }) => {
    await serveApi(page)
    const dialog = await openDialog(page, tab, opener)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    // Focus returns to the button that opened it, so keyboard users keep their place.
    await expect(page.getByRole('button', { name: opener }).first()).toBeFocused()
  })
}

test('importing game data sends the file as it is, and shows the bags and quest log (#185)', async ({ page }) => {
  const sent = await serveApi(page)
  await openTab(page, 'character')
  const bags = page.getByRole('region', { name: 'Bags' })
  await expect(bags.getByRole('link', { name: 'Kindlegem Girdle' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Bank' })).toContainText('Empty.') // the schema example's bank: seen, and empty
  await page.getByRole('button', { name: 'Import again' }).click()
  const file = { name: 'CharacterPlannerExport.lua', mimeType: 'text/plain', buffer: Buffer.from('X = 1') }
  await page.locator('dialog[open] input[type="file"]').setInputFiles(file)
  await expect(page.locator('dialog[open]')).toContainText('Imported: Brumboldt')
  const upload = sent.find((r) => r.method() === 'POST' && r.url().endsWith('/api/game-data'))!
  expect(upload.postData()).toBe('X = 1')
  expect(upload.headers()['content-type']).toBe('application/octet-stream')
  await page.keyboard.press('Escape')
  await openTab(page, 'plan')
  await expect(
    page.getByRole('region', { name: 'Quest log' }).getByRole('link', { name: 'The Summoning' }),
  ).toBeVisible()
})
