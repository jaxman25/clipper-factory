import LoginForm from '@/components/studio/LoginForm'
import { publicProviders } from '@/lib/next-auth'

export const metadata = {
  title: 'Sign in',
}

/** Only allow same-origin callback paths to avoid an open redirect. */
function safeCallback(value) {
  const target = String(value || '')
  if (target.startsWith('/') && !target.startsWith('//')) return target
  return '/dashboard'
}

export default function LoginPage({ searchParams }) {
  const error = String(searchParams?.error || '')
  const callbackUrl = safeCallback(searchParams?.callbackUrl)
  const googleConfigured = publicProviders().some((provider) => provider.id === 'google')

  return (
    <>
      <LoginForm
        googleConfigured={googleConfigured}
        callbackUrl={callbackUrl}
        initialError={error}
        pageType="login"
      />
      {/* Signup link at bottom for users without an account */}
      <div className="mt-8 text-center">
        <a
          href="/signup"
          className="text-[11px] uppercase tracking-widest text-brand hover:text-brand/90 transition-colors"
        >
          Don't have an account? Sign up here
        </a>
      </div>
    </>
  )
}