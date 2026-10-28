import LoginForm from '@/components/studio/LoginForm'

export const metadata = {
  title: 'Sign up',
}

export default function SignupPage() {
  return (
    <>
      <LoginForm
        pageType="signup"
      />
      {/* Already have an account? Log in here */}
      <div className="mt-8 text-center">
        <a
          href="/login"
          className="text-[11px] uppercase tracking-widest text-brand hover:text-brand/90 transition-colors"
        >
          Already have an account? Log in here
        </a>
      </div>
    </>
  )
}