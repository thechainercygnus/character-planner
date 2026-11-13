import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Coverage (#55), with `npm run coverage`. The floors (#94) are the values measured
    // on 2026-11-13, rounded down: a PR that lowers coverage fails. Raise them as it grows.
    coverage: {
      thresholds: { statements: 91, branches: 81, functions: 87, lines: 93 },
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      // main.tsx only mounts the app; it has nothing to test.
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/vite-env.d.ts', 'src/main.tsx'],
      reporter: ['text-summary', 'json-summary', 'lcov'],
    },
  },
})
