/** What a tap on a touch screen shows (#153): helpers for TouchTips. */

/** How long a tip stays up after a tap. */
export const TIP_MS = 4000
export const TIP_WIDTH = 280
export const EDGE = 8

/** Elements whose tap does something: their title isn't shown, unless they're disabled. */
const ACTIONS = 'button, a, input, select, textarea, summary'

/** The tooltip a tap should show, if any: a title on a non-action, or on a disabled one. */
export function tipFor(target: EventTarget | null): { text: string; anchor: Element } | null {
  if (!(target instanceof Element)) return null
  const anchor = target.closest('[title]')
  const text = anchor?.getAttribute('title')
  if (!anchor || !text) return null
  const action = anchor.closest(ACTIONS)
  if (action && action.getAttribute('aria-disabled') !== 'true' && !action.hasAttribute('disabled')) {
    return null
  }
  return { text, anchor }
}
