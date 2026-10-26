'use client';

import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { cn } from '@/lib/cn';

const STORAGE_KEY = 'theme';

/**
 * Light/dark switch for the palette themes defined in app/globals.css.
 *
 * The first render always assumes dark so server and client markup match; the
 * inline script in app/layout.js has already applied the stored (or system)
 * theme to <html> before hydration, so one effect tick syncs the icon.
 */
export default function ThemeToggle({ className }) {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  }, []);

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (err) {
      /* private browsing: the choice simply will not persist */
    }
  }

  const nextTheme = theme === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${nextTheme} mode`}
      title={`Switch to ${nextTheme} mode`}
      className={cn(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line text-muted transition hover:bg-wash-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50',
        className
      )}
    >
      {theme === 'dark' ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}
