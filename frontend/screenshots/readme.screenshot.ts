import { writeFile } from 'node:fs/promises'
import { test } from '@playwright/test'
import { openTab, serveApi } from '../e2e/support.ts'

/**
 * The README's and the docs site's screenshot (#252): the Upgrades tab, served from the
 * e2e fixtures (recorded responses for the example character, already public in this
 * repository), so it needs no instance and no Battle.net. `npm run screenshot` retakes it
 * after a UI change.
 *
 * Taken at 2x for sharpness, then encoded as WebP in the browser itself (a canvas), so the
 * file stays small without an image library.
 */
const OUT = new URL('../../docs/_static/planner-upgrades.webp', import.meta.url)
const QUALITY = 0.82

test.use({ viewport: { width: 1200, height: 760 }, deviceScaleFactor: 2, colorScheme: 'dark' })

test('the Upgrades tab, for the README', async ({ page }) => {
  await serveApi(page)
  await openTab(page, 'upgrades')
  await page.getByRole('heading', { name: /Recommended upgrades/ }).waitFor()
  // Images (item icons) loaded, and nothing still moving.
  await page.waitForFunction(() => [...document.images].every((img) => img.complete))
  const png = await page.screenshot({ type: 'png' })
  const webp = await page.evaluate(
    async ({ data, quality }) => {
      const image = new Image()
      image.src = `data:image/png;base64,${data}`
      await image.decode()
      const canvas = document.createElement('canvas')
      canvas.width = image.naturalWidth
      canvas.height = image.naturalHeight
      canvas.getContext('2d')!.drawImage(image, 0, 0)
      return canvas.toDataURL('image/webp', quality).split(',')[1]!
    },
    { data: png.toString('base64'), quality: QUALITY },
  )
  await writeFile(OUT, Buffer.from(webp, 'base64'))
})
