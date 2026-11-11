import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TabBar, useHashTab, type Tab } from './Tabs'

type Id = 'one' | 'two'
const TABS: readonly Tab<Id>[] = [
  { id: 'one', label: 'One' },
  { id: 'two', label: 'Two' },
]

function Harness() {
  const [active, select] = useHashTab(TABS, 'one')
  return (
    <>
      <TabBar tabs={TABS} active={active} onSelect={select} counts={{ two: 3 }} />
      <p>showing {active}</p>
    </>
  )
}

describe('tabs', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('starts on the fallback and switches on click, recording the hash', () => {
    render(<Harness />)
    expect(screen.getByText('showing one')).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: /Two/ }))

    expect(screen.getByText('showing two')).toBeTruthy()
    expect(window.location.hash).toBe('#two')
    expect(screen.getByRole('tab', { name: /Two/ }).getAttribute('aria-selected')).toBe('true')
  })

  it('opens the tab named in the hash', () => {
    window.history.replaceState(null, '', '#two')
    render(<Harness />)
    expect(screen.getByText('showing two')).toBeTruthy()
  })

  it('ignores unknown hashes', () => {
    window.history.replaceState(null, '', '#nope')
    render(<Harness />)
    expect(screen.getByText('showing one')).toBeTruthy()
  })
})
