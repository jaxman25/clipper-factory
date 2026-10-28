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
    <LoginForm
      googleConfigured={googleConfigured}
      callbackUrl={callbackUrl}
      initialError={error}
      headerText="Welcome Back"
      subHeaderText="Sign in to generate and schedule shorts."
      submitButtonText="Sign In"
      googleButtonText="Continue with Google"
      bottomLinkText="Don't have an account? Sign up"
      linkHref="/signup"
      showCreditsText={false}
    />
  )
}