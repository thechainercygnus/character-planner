import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ItemLink } from './ItemLink'

const GIRDLE = 'https://www.wowhead.com/forever/item=270230'

describe('ItemLink', () => {
  it("links the name to the item's Wowhead page in a new tab", () => {
    render(<ItemLink href={GIRDLE}>Kindlegem Girdle</ItemLink>)
    const link = screen.getByRole('link', { name: 'Kindlegem Girdle' })
    expect(link.getAttribute('href')).toBe(GIRDLE)
    expect(link.getAttribute('target')).toBe('_blank')
    // No referrer: the page learns nothing about the planner or the character.
    expect(link.getAttribute('rel')).toBe('noreferrer')
    expect(link.className).toBe('item-link')
  })

  it('is plain text when there is no page, keeping its title', () => {
    const { container } = render(
      <ItemLink href={null} title="Gives +1 Agility">
        Lesser Agility
      </ItemLink>,
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Lesser Agility').getAttribute('title')).toBe('Gives +1 Agility')
    render(<ItemLink href={undefined}>Bare</ItemLink>, { container })
    expect(screen.getByText('Bare')).toBeTruthy()
  })

  it('takes a name of its own when its text is only an arrow', () => {
    render(
      <ItemLink href={GIRDLE} label="Kindlegem Girdle on Wowhead">
        ↗
      </ItemLink>,
    )
    expect(screen.getByRole('link', { name: 'Kindlegem Girdle on Wowhead' })).toBeTruthy()
  })

  it("doesn't pass a click on to the row around it", () => {
    const row = vi.fn()
    render(
      // A clickable row, as on the Upgrades tab.
      // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
      <div onClick={row}>
        <ItemLink href={GIRDLE}>Kindlegem Girdle</ItemLink>
      </div>,
    )
    fireEvent.click(screen.getByRole('link'))
    expect(row).not.toHaveBeenCalled()
  })
})
