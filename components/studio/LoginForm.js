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
          className={busy
            ? 'btn mt-5 w-full flex items-center justify-center gap-2 disabled:opacity-50'
            : googleConfigured
              ? 'btn mt-5 w-full flex items-center justify-center gap-2 bg-white border border-line text-fg hover:bg-gray-50'
              : 'btn mt-5 w-full flex items-center justify-center gap-2 bg-white border border-line text-fg cursor-not-allowed'
          }
          disabled={busy || !googleConfigured}
          aria-disabled={busy || !googleConfigured}
          onClick={() => googleConfigured && signIn('google', { callbackUrl })}
          title={!googleConfigured && 'Google login not configured yet'}
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="#ffb400"
            stroke="#ffb400"
          >
            <path d="M21.43 13.07a7.96 7.96 0 0 1-1.83-.05l-2.16 2.16a5.99 5.99 0 0 1-1.41-1.41l2.23-2.23a1.73 1.73 0 0 1 0 2.45l-2.26 2.26a11.95 11.95 0 0 1-1.66 1.25l-.58-.03a5.96 5.96 0 0 1-.27-1.27l-.26-.65a7.94 7.94 0 0 1-1.06-1.06l-.63 2.36a9.92 9.92 0 0 1-1.41-.83l-.78-.36a7.99 7.99 0 0 1-1.01-1.15l-.66-2.05a12.02 12.02 0 0 1-.55-1.95l-.28-.32a7.93 7.93 0 0 1-1.1-.62l-.63-2.36a9.88 9.88 0 0 1-.71-1.36l-.37-.85a7.96 7.96 0 0 1-.52-1.38l-.28-.82a5.98 5.98 0 0 1-.28-1.26l1.05-2.02a7.99 7.99 0 0 1 .82-1.13l.34-1.88a5.96 5.96 0 0 1 .63-.58l2.23 2.16a5.99 5.99 0 0 1 1.41 1.41l-2.16-2.16a7.96 7.96 0 0 1-1.05.05l-2.35 2.38a5.95 5.95 0 0 1-1.23 1.21l-.57.04a5.95 5.95 0 0 1-.32.27l-.23.66a7.97 7.97 0 0 1-1.15 1.01l-.37.78a9.91 9.91 0 0 1-.83 1.41l-.36.78a7.99 7.99 0 0 1-1.01 1.15l.79 2.06a12.02 12.02 0 0 1 .07 1.57l.33.33a7.96 7.96 0 0 1 .66 1.13l.76 2.33a9.89 9.89 0 0 1 1.35.77l.36.1a7.99 7.99 0 0 1 1.16.58l2.24-2.16a5.95 5.95 0 0 1 1.24-.82l.33-.39a7.99 7.99 0 0 1 1.12-.3l.31-1.75a5.99 5.99 0 0 1 .58-.31l2.23-2.16ZM12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Z" />
          </svg>
          <span>{googleConfigured ? 'Continue with Google' : 'Google login not configured'}</span>
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