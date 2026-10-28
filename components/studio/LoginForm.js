'use client'

import { useState } from 'react'
import { signIn } from 'next-auth/react'
import { Loader2 } from 'lucide-react'

const ERROR_TEXT = {
  CredentialsSignin: 'Wrong email or password.',
  OAuthAccountNotLinked: 'That Google account is already linked to another sign-in method.',
  OAuthCallback: 'Google sign-in was cancelled or failed. Try again.',
  Configuration: 'Sign-in is not configured yet (check NEXTAUTH_SECRET and Google credentials).',
  AccessDenied: 'This account is not allowed to sign in.',
}

function describeError(code) {
  if (!code) return ''
  return ERROR_TEXT[code] || 'Sign-in failed. Please try again.'
}

/**
 * Login form: Google button (disabled with a tooltip when Google OAuth is
 * not configured) + email/password.
 * pageType='login' shows "Welcome Back" context; pageType='signup' shows
 * "Create an Account" context. The underlying credentials flow already creates
 * an account on first sign-in.
 * Failures come back as ?error=<code> on the URL, mapped to friendly text.
 */
export default function LoginForm({
  googleConfigured = false,
  callbackUrl = '/dashboard',
  initialError = '',
  pageType = 'login',
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState('')

  const error = describeError(initialError) || localError

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    if (!email.trim() || !password) {
      setLocalError('Enter your email and password.')
      return
    }
    setBusy(true)
    setLocalError('')
    try {
      // redirect:true navigates to callbackUrl on success and reloads this
      // page with ?error=... on failure.
      await signIn('credentials', { email: email.trim(), password, callbackUrl })
    } catch (err) {
      setLocalError('Could not reach the sign-in service.')
      setBusy(false)
    }
  }

  // Determine header text based on page type
  const headerText = pageType === 'signup' ? 'Create an Account' : 'Welcome Back'
  const subHeaderText = pageType === 'signup'
    ? 'Sign in to generate and schedule shorts.'
    : 'Sign in to generate and schedule shorts.'

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-5 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-surface p-7 shadow-card">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand/15 text-lg font-black text-brand">
            CF
          </span>
          <div>
            <h1 className="text-lg font-bold text-fg">{headerText}</h1>
            <p className="text-xs text-muted">{subHeaderText}</p>
          </div>
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-xs font-semibold text-danger">
            {error}
          </p>
        ) : null}

        <button
          type="button"
          className="btn mt-5 w-full"
          disabled={busy || !googleConfigured}
          title={googleConfigured ? undefined : 'Google login not configured yet'}
          aria-disabled={busy || !googleConfigured}
          onClick={() => googleConfigured && signIn('google', { callbackUrl })}
        >
          Continue with Google
        </button>

        <div className="my-4 flex items-center gap-3">
          <span className="h-px flex-1 bg-line" />
          <span className="text-[11px] uppercase tracking-widest text-subtle">or</span>
          <span className="h-px flex-1 bg-line" />
        </div>

        

        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="label">Email</span>
            <input
              className="input"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={busy}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
            />
          </label>
          <button type="submit" className="btn btn-primary mt-1 w-full" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {busy ? 'Signing in…' : 'Sign In / Sign Up'}
          </button>
        </form>

        {pageType === 'signup' && (
          <p className="text-xs leading-relaxed text-muted">
            Don't have an account? Just enter your email and a password, and we will create one for you.
          </p>
        )}

        <p className="mt-4 text-center text-[11px] leading-relaxed text-subtle">
          New accounts start with <b className="text-muted">5 free credits</b>.
        </p>
      </div>
    </div>
  )
}