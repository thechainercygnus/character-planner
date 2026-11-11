import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest doesn't expose globals here, so Testing Library can't register its own cleanup.
afterEach(() => {
  cleanup()
})

// jsdom has <dialog> but not showModal()/close(). Shim just enough for tests:
// toggle `open` and fire the `close` event that React's onClose listens for.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    if (!this.open) return
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
}
