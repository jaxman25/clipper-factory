/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx}', './components/**/*.{js,jsx}', './lib/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0A0A0B',
        surface: '#161618',
        raised: '#1C1C1F',
        line: 'rgba(255,255,255,0.10)',
        muted: '#A1A1AA',
        brand: {
          DEFAULT: '#2F80ED',
          dark: '#0F4CCF',
          soft: 'rgba(47,128,237,0.14)',
        },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 0 rgba(255,255,255,0.04) inset, 0 20px 40px -24px rgba(0,0,0,0.8)',
        glow: '0 16px 40px -18px rgba(47,128,237,0.55)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
        rise: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s linear infinite',
        rise: 'rise 0.35s ease-out both',
      },
    },
  },
  plugins: [],
};
