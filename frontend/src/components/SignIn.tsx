/** With users on (#16, ADR 0037), what a signed-out visitor sees: the Battle.net sign-in. */
export function SignIn({ signupsOpen }: { signupsOpen: boolean }) {
  return (
    <section className="sign-in">
      <h1>Character Planner</h1>
      <p>Sign in with your Battle.net account to see your characters.</p>
      <p>
        <a className="button" href="/auth/login">
          Sign in with Battle.net
        </a>
      </p>
      <p className="muted">
        {signupsOpen
          ? 'New here? Signing in creates your account.'
          : 'This instance is invite-only: ask the person who runs it to open sign-ups.'}{' '}
        Or try <a href="#guest">guest mode</a>, which needs no account.
      </p>
    </section>
  )
}
