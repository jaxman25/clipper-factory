/**
 * Semantic tokens resolve to CSS variables defined in app/globals.css.
 *
 * Palette #2 (warm coffee):
 *   #211B1A → #382A28 → #60433D → #916B60 → #C1A094 → #EBD8CE
 *
 * Dark is the default; [data-theme='light'] re-points the same variables, so
 * every utility below follows the active theme without conditional classes.
 */
const tone = (name) => `rgb(var(--${name}-rgb) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx}', './components/**/*.{js,jsx}', './lib/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: tone('ink'),
        rail: tone('rail'),
        surface: tone('surface'),
        raised: tone('raised'),
        field: tone('field'),
        line: tone('line'),
        fg: tone('fg'),
        muted: tone('muted'),
        subtle: tone('subtle'),
        onbrand: tone('onbrand'),
        wash: 'var(--wash)',
        'wash-strong': 'var(--wash-strong)',
        brand: {
          DEFAULT: tone('brand'),
          hover: tone('brand-hover'),
          soft: 'var(--brand-soft)',
        },
        danger: tone('danger'),
        warn: tone('warn'),
        ok: tone('ok'),
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        glow: 'var(--shadow-glow)',
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
