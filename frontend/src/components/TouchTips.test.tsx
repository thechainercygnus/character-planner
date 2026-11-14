import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TIP_MS, tipFor } from '../touchTip'
import { TouchTips } from './TouchTips'

/** A pointerup as a finger (or a mouse) would send it. */
function tap(target: Element, pointerType: 'touch' | 'mouse' = 'touch') {
  const event = new Event('pointerup', { bubbles: true })
  Object.defineProperty(event, 'pointerType', { value: pointerType })
  act(() => {
    target.dispatchEvent(event)
  })
}

function page(html: string) {
  document.body.insertAdjacentHTML('beforeend', `<div id="page">${html}</div>`)
  return document.getElementById('page')!
}

describe('tipFor', () => {
  afterEach(() => document.getElementById('page')?.remove())

  it('shows the title of what was tapped, or of what it sits in', () => {
    const root = page('<span title="Average of 13 slots"><b>16.7</b></span>')
    expect(tipFor(root.querySelector('b'))?.text).toBe('Average of 13 slots')
  })

  it('leaves buttons and links alone: a tap there is an action', () => {
    const root = page('<button title="Refresh it">Refresh</button><a href="#x" title="Go">Go</a>')
    expect(tipFor(root.querySelector('button'))).toBeNull()
    expect(tipFor(root.querySelector('a'))).toBeNull()
  })

  it('shows it on a disabled button, where a tap does nothing (talents outside editing)', () => {
    const root = page('<button aria-disabled="true" title="Shield Wall: 2 of 3">SW</button>')
    expect(tipFor(root.querySelector('button'))?.text).toBe('Shield Wall: 2 of 3')
  })

  it('and on labels, which explain a setting', () => {
    const root = page('<label title="Include items within this many levels">Levels ahead</label>')
    expect(tipFor(root.querySelector('label'))?.text).toBe('Include items within this many levels')
  })

  it('needs a title', () => {
    expect(tipFor(page('<span>plain</span>').querySelector('span'))).toBeNull()
    expect(tipFor(null)).toBeNull()
  })
})

describe('TouchTips', () => {
  afterEach(() => {
    vi.useRealTimers()
    document.getElementById('page')?.remove()
  })

  it('shows a tapped tooltip, then hides it after a while', () => {
    vi.useFakeTimers()
    render(<TouchTips />)
    const root = page('<span title="Weighted stat score vs what you wear">+6.0</span>')
    tap(root.querySelector('span')!)
    expect(screen.getByRole('status').textContent).toBe('Weighted stat score vs what you wear')
    act(() => {
      vi.advanceTimersByTime(TIP_MS)
    })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('leaves mouse users to the browser, and hides on a tap elsewhere', () => {
    render(<TouchTips />)
    const root = page('<span title="A tip">x</span><p>elsewhere</p>')
    tap(root.querySelector('span')!, 'mouse')
    expect(screen.queryByRole('status')).toBeNull()
    tap(root.querySelector('span')!)
    expect(screen.getByRole('status')).toBeTruthy()
    tap(root.querySelector('p')!)
    expect(screen.queryByRole('status')).toBeNull()
  })
})
