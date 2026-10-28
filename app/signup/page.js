import LoginForm from '@/components/studio/LoginForm'
import { publicProviders } from '@/lib/next-auth'

export const metadata = {
  title: 'Sign up',
}

/** Only allow same-origin callback paths to avoid an open redirect. */
function safeCallback(value) {
  const target = String(value || '')
  if (target.startsWith('/') && !target.startsWith('//')) return target
  return '/dashboard'
}

export default function SignupPage({ searchParams }) {
  const error = String(searchParams?.error || '')
  const callbackUrl = safeCallback(searchParams?.callbackUrl)
  const googleConfigured = publicProviders().some((provider) => provider.id === 'google')

  return (
    <LoginForm
      mode="signup"
      googleConfigured={googleConfigured}
      callbackUrl={callbackUrl}
      initialError={error}
    />
  )
}