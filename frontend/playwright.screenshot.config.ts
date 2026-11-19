import { defineConfig, devices } from '@playwright/test'
import base from './playwright.config.ts'

/**
 * The README's screenshot (#252): `npm run screenshot` builds the app, serves it as the
 * browser checks do, and writes docs/_static/planner-upgrades.webp. Kept apart from
 * `npm run e2e`, which checks the app and writes nothing.
 */
export default defineConfig({
  ...base,
  testDir: 'screenshots',
  testMatch: '*.screenshot.ts',
  fullyParallel: false,
  reporter: 'list',
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
