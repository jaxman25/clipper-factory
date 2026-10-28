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
 * Login form: email/password + optional Google sign-in.
 * Used by both /login and /signup pages with different text labels.
 */
export default function LoginForm({
  googleConfigured = false,
  callbackUrl = '/dashboard',
  initialError = '',
  // Text labels customized by the caller
  headerText,
  subHeaderText,
  submitButtonText,
  googleButtonText,
  bottomLinkText,
  linkHref,
  showCreditsText = false,
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

        <button
          type="button"
          className={busy
            ? 'btn mt-5 w-full flex items-center justify-center gap-2 disabled:opacity-50'
            : googleConfigured
              ? 'btn mt-5 w-full flex items-center justify-center gap-2 bg-white border border-gray-300 text-gray-900 hover:bg-gray-50'
              : 'btn mt-5 w-full flex items-center justify-center gap-2 bg-white border border-gray-300 text-gray-900 cursor-not-allowed'
          }
          disabled={busy || !googleConfigured}
          aria-disabled={busy || !googleConfigured}
          onClick={() => googleConfigured && signIn('google', { callbackUrl })}
          title={!googleConfigured && 'Google login not configured yet'}
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="#ea4335"
            stroke="#ea4335"
          >
            <path d="M12 2c-5.52 0-10 4.48-10 10s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0-2C-6.63 8 2 2 2 8s8.63 4 8.63-4S-4.63 4 2 4zm0 9.59c-3.87 0-7 .98-7 3.5s3.13 3.5 7 3.5 7-.98 7-3.5-3.13-3.5-7-3.5zM12 5.5c2.12 0 3.85.97 4.93 2.28l3.16 1.85c.12.09.18.14.24.22.09.12.13.22.13.35 0 .21-.06.34-.14.44l-1.32 1.75c-.34.45-.98.77-1.65.77-1.1 0-1.66-.6-1.66-1.75l-1.33-1.75c-.08-.1-.15-.23-.18-.41 0-.21 0-.41 0-.5 0-.21 0-.36 0-.5 0l-.31-1.75c-1.48-.86-2.47-2.15-2.47-3.73 0-1.62.65-2.88 1.75-3.73l3.13-1.86c.11-.09.16-.14.23-.18.07-.05.09-.1.09-.15z"/>
          </svg>
          <span>{googleConfigured ? googleButtonText : 'Google login not configured'}</span>
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
            {busy ? 'Signing in…' : submitButtonText}
          </button>
        </form>

        {showCreditsText && (
          <p className="mt-4 text-center text-[11px] leading-relaxed text-subtle">
            New accounts start with <b className="text-muted">5 free credits</b>.
          </p>
        )}

        {bottomLinkText && (
          <a
            href={linkHref || '/signup'}
            className="mt-4 text-center text-[11px] uppercase tracking-widest text-brand hover:text-brand/90 transition-colors"
          >
            {bottomLinkText}
          </a>
        )}
      </div>
    </div>
  )
}