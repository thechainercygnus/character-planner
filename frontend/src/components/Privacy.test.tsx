import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { About } from '../api'
import { Contact, Privacy } from './Privacy'

const about = (operator_contact: string): About => ({
  version: '0.3.0',
  source_url: 'https://github.com/thechainercygnus/character-planner',
  operator_contact,
  data: {
    name: 'Forever Companion',
    url: 'https://forevercompanion.io',
    sources: [],
  },
})

function renderPrivacy(contact: string) {
  const calls: { url: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' })
      if (url === '/api/character') return Response.json({ removed: { snapshot: 7, itemchoice: 2 } })
      return Response.json(about(contact))
    }),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <Privacy />
    </QueryClientProvider>,
  )
  return calls
}

describe('Privacy', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("names the operator's contact and what's stored, for how long", async () => {
    renderPrivacy('admin@example.org')
    const links = await screen.findAllByRole('link', {
      name: 'admin@example.org',
    })
    expect(links[0]?.getAttribute('href')).toBe('mailto:admin@example.org')
    for (const heading of ["What's stored", 'How long', 'Who can see it', 'Sharing', 'Removing it']) {
      expect(screen.getByRole('heading', { name: heading })).toBeTruthy()
    }
    expect(screen.getByText(/kept for at most 30 days/)).toBeTruthy()
  })

  it('deletes the data only after a second click', async () => {
    const calls = renderPrivacy('')
    fireEvent.click(screen.getByRole('button', { name: "Delete the character's data" }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: "Delete the character's data" }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes, delete everything' }))
    expect((await screen.findByRole('status')).textContent).toBe(
      'Deleted 9 stored rows. The next sync fetches the character again.',
    )
    expect(calls).toContainEqual({ url: '/api/character', method: 'DELETE' })
  })
})

describe('Contact', () => {
  it('links a web address, and shows anything else as text', () => {
    const { container, rerender } = render(<Contact value="https://example.org/contact" />)
    expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.org/contact')
    rerender(<Contact value="javascript:alert(1)" />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(container.textContent).toBe('javascript:alert(1)')
    rerender(<Contact value="" />)
    expect(container.textContent).toBe('the person who runs this instance')
  })
})
