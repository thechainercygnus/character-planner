import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest doesn't expose globals here, so Testing Library can't register its own cleanup.
afterEach(() => {
  cleanup()
})
