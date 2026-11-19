import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

/** The token from an invite link's #invite= fragment (#239), which never reaches the server's logs. */
function inviteToken(): string | null {
  const match = /^#invite=([^&]+)$/.exec(window.location.hash)
  return match ? decodeURIComponent(match[1]!) : null
}

/**
 * With users on (#16, ADR 0037), what a signed-out visitor sees: the Battle.net sign-in. An
 * invite link (#239) is held for the sign-in that follows, so it can create an account while
 * sign-ups are closed.
 */
export function SignIn({ signupsOpen }: { signupsOpen: boolean }) {
  const token = inviteToken()
  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: async () => {
      await api.acceptInvite(token!)
      return true
    },
    enabled: token !== null,
    retry: false,
    staleTime: Infinity,
  })
  return (
    <section className="sign-in">
      <h1>Character Planner</h1>
      {invite.isSuccess && (
        <p role="status">
          <strong>You've been invited.</strong> Sign in with Battle.net to create your account.
        </p>
      )}
      {invite.isError && (
        <p className="error" role="alert">
          {invite.error.message}
        </p>
      )}
      <p>Sign in with your Battle.net account to see your characters.</p>
      <p>
        <a className="button" href="/auth/login">
          Sign in with Battle.net
        </a>
      </p>
      {!invite.isSuccess && (
        <p className="muted">
          {signupsOpen
            ? 'New here? Signing in creates your account.'
            : 'This instance is invite-only: ask the person who runs it for an invite link.'}{' '}
          Or try <a href="#guest">guest mode</a>, which needs no account.
        </p>
      )}
    </section>
  )
}
