'use client'

import { useState } from 'react'
import Link from 'next/link'
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

/** Official Google "G" logo, 4-color (blue, green, yellow, red). */
function GoogleLogo() {
  return (
    <svg className="h-5 w-5 shrink-0" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  )
}

/**
 * Shared auth form for /login (mode="login") and /signup (mode="signup").
 * The credentials provider creates the account on first sign-in, so the
 * signup mode uses the same signIn('credentials') flow as login.
 * Failures come back as ?error=<code> on the URL, mapped to friendly text.
 */
export default function LoginForm({
  mode = 'login',
  googleConfigured = false,
  callbackUrl = '/dashboard',
  initialError = '',
}) {
  const isSignup = mode === 'signup'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState('')

  const error = describeError(initialError) || localError

  const headerText = isSignup ? 'Create an Account' : 'Welcome Back'
  const subHeaderText = isSignup
    ? 'Create your account to start generating shorts.'
    : 'Sign in to generate and schedule shorts.'
  const submitText = isSignup ? 'Sign Up' : 'Sign In'
  const googleText = isSignup ? 'Sign up with Google' : 'Continue with Google'
  const bottomLinkText = isSignup
    ? 'Already have an account? Log in'
    : "Don't have an account? Sign up"
  const bottomLinkHref = isSignup ? '/login' : '/signup'
  const passwordAutoComplete = isSignup ? 'new-password' : 'current-password'

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

        {/* Standard Google sign-in button: white bg, light grey border, dark text. */}
        <button
          type="button"
          onClick={() => googleConfigured && signIn('google', { callbackUrl })}
          disabled={busy || !googleConfigured}
          aria-disabled={busy || !googleConfigured}
          title={googleConfigured ? undefined : 'Google login not configured yet'}
          className={`btn mt-5 w-full flex items-center justify-center gap-2.5 bg-white border border-gray-300 text-gray-900 hover:bg-gray-50 ${
            busy || !googleConfigured ? 'cursor-not-allowed opacity-60' : ''
          }`}
        >
          <GoogleLogo />
          <span>{googleText}</span>
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
              autoComplete={passwordAutoComplete}
              placeholder="••••••••"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
            />
          </label>
          <button type="submit" className="btn btn-primary mt-1 w-full" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {busy ? (isSignup ? 'Creating account…' : 'Signing in…') : submitText}
          </button>
        </form>

        {isSignup ? (
          <p className="mt-4 text-center text-[11px] leading-relaxed text-subtle">
            New accounts start with <b className="text-muted">5 free credits</b>.
          </p>
        ) : null}

        <p className="mt-4 text-center">
          <Link
            href={bottomLinkHref}
            className="text-[11px] uppercase tracking-widest text-brand hover:text-brand/90 transition-colors"
          >
            {bottomLinkText}
          </Link>
        </p>
      </div>
    </div>
  )
}