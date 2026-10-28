import LoginForm from '@/components/studio/LoginForm'

export const metadata = {
  title: 'Sign up',
}

export default function SignupPage() {
  return (
    <LoginForm
      headerText="Create an Account"
      subHeaderText="Sign in to generate and schedule shorts."
      submitButtonText="Sign Up"
      googleButtonText="Sign up with Google"
      bottomLinkText="Already have an account? Log in"
      showCreditsText={true}
    />
  )
}