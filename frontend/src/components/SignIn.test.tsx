import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignIn } from './SignIn'

function show(answer: Response) {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      posts.push({ url, body: JSON.parse(String(init?.body)) as unknown })
      return answer
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SignIn signupsOpen={false} />
    </QueryClientProvider>,
  )
  return posts
}

describe('SignIn', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.location.hash = ''
  })

  it('says the instance is invite-only when sign-ups are closed', () => {
    show(new Response(null, { status: 204 }))
    expect(screen.getByText(/invite-only: ask the person who runs it for an invite link/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Sign in with Battle.net' }).getAttribute('href')).toBe('/auth/login')
  })

  it('holds an invite from the link for the sign-in that follows (#239)', async () => {
    window.location.hash = '#invite=a-token-of-thirty-two-characters'
    const posts = show(new Response(null, { status: 204 }))
    expect(await screen.findByText("You've been invited.")).toBeTruthy()
    expect(posts).toEqual([{ url: '/auth/invite', body: { token: 'a-token-of-thirty-two-characters' } }])
    expect(screen.queryByText(/invite-only/)).toBeNull()
  })

  it("says when an invite can't be used", async () => {
    window.location.hash = '#invite=a-spent-token-of-thirty-two-chars'
    show(
      Response.json(
        { detail: 'This invite has been used, revoked or has expired: ask for a new one' },
        { status: 404 },
      ),
    )
    expect((await screen.findByRole('alert')).textContent).toContain('used, revoked or has expired')
  })
})
