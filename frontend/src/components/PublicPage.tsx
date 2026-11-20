import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api, publicLink, type PublicPageState } from '../api'
import { CharacterHeader } from './CharacterPanels'
import { CharacterSnapshot } from './CharacterSnapshot'
import { Footer } from './Footer'

/**
 * A character's public page (#42, ADR 0063), for anyone with its link: the last sync's
 * snapshot, read-only. It needs no sign-in, and shows nothing of the rest of the planner.
 */
export function PublicPage({ token }: { token: string }) {
  const page = useQuery({
    queryKey: ['public-character', token],
    queryFn: () => api.publicCharacter(token),
    retry: false,
  })
  const gone = page.error instanceof ApiError && page.error.status === 404
  return (
    <main>
      {page.isPending && <p className="muted">Loading character…</p>}
      {page.isError && (
        <p className="error">
          {gone ? "This page isn't shared, or its link has changed." : `Couldn't load this page: ${page.error.message}`}
        </p>
      )}
      {page.data &&
        (page.data.level === null ? (
          <p className="muted">There's nothing to show yet: this character hasn't been synced in the last 30 days.</p>
        ) : (
          <>
            <CharacterHeader character={{ ...page.data, level_source: null }} />
            <p className="muted">A public page, shared by this character's owner from their Character Planner.</p>
            <CharacterSnapshot character={{ ...page.data, level_source: null }} />
          </>
        ))}
      <Footer />
    </main>
  )
}

/** On the Character tab: the owner turns the public page on or off, and copies its link. */
export function PublicPageControl() {
  const queryClient = useQueryClient()
  const state = useQuery({ queryKey: ['public-page'], queryFn: api.publicPage })
  const [copied, setCopied] = useState(false)
  const done = (next: PublicPageState) => {
    queryClient.setQueryData(['public-page'], next)
    setCopied(false)
  }
  const toggle = useMutation({ mutationFn: api.setPublicPage, onSuccess: done })
  const regenerate = useMutation({ mutationFn: api.regeneratePublicPage, onSuccess: done })
  const link = state.data?.token ? publicLink(state.data.token) : null
  const error = toggle.error ?? regenerate.error

  return (
    <section className="public-page" aria-labelledby="public-page-heading">
      <h2 id="public-page-heading">Public page</h2>
      <p className="muted">
        Share this character with anyone who has the link, no sign-in needed: talents, equipment, stats and professions
        as of the last sync. Never your plans, settings, account or other characters.
      </p>
      {state.isError && <p className="error">Couldn't load the public page: {state.error.message}</p>}
      {state.data && (
        <label>
          <input
            type="checkbox"
            checked={state.data.enabled}
            disabled={toggle.isPending}
            onChange={(event) => toggle.mutate(event.target.checked)}
          />{' '}
          Share a public page
        </label>
      )}
      {error && <p className="error">{error.message}</p>}
      {link && (
        <div className="public-link">
          <input readOnly value={link} aria-label="Public page link" onFocus={(event) => event.target.select()} />{' '}
          <button
            type="button"
            className="secondary"
            onClick={() => {
              void navigator.clipboard?.writeText(link).then(() => setCopied(true))
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>{' '}
          <button
            type="button"
            className="secondary"
            onClick={() => regenerate.mutate()}
            disabled={regenerate.isPending}
            title="The old link stops working"
          >
            New link
          </button>
          <p className="muted">Turning it off, or making a new link, stops the old link working.</p>
        </div>
      )}
    </section>
  )
}
