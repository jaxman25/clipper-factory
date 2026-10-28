'use client';

import { useEffect, useRef, useState } from 'react';
import { signOut } from 'next-auth/react';
import { ChevronDown, Crown, Loader2, LogOut } from 'lucide-react';

/**
 * Account menu in the dashboard's top-right corner (spec 04 UI):
 *  - trigger = circular avatar with the email's initial (mobile collapses to
 *    just this icon; the chevron only shows from sm up)
 *  - dropdown = avatar + email, then the status card:
 *      Admin  -> golden "Admin (Unlimited Credits)" pill
 *      Public -> "X Credits Left" + Buy Credits ("Coming Soon")
 *  - Sign out lives inside the dropdown (hidden on localhost, where login is
 *    bypassed and there is no session to end)
 *
 * Reads /api/credits (sessions + localhost bypass) and re-reads whenever the
 * tab regains focus so a spent balance never shows stale after a generation.
 */
export default function UserBadge() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const response = await fetch('/api/credits', { cache: 'no-store' });
        if (!response.ok) {
          if (alive) {
            setFailed(true);
            setData(null);
          }
          return;
        }
        const payload = await response.json();
        if (alive) {
          setData(payload);
          setFailed(false);
        }
      } catch (err) {
        if (alive) setFailed(true);
      }
    }

    load();
    const onFocus = () => load();
    window.addEventListener('focus', onFocus);
    return () => {
      alive = false;
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (failed) return null;

  const initial = data?.email ? String(data.email).trim().charAt(0).toUpperCase() || '?' : '?';

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex items-center gap-1 rounded-full border border-line bg-surface p-0.5 transition hover:bg-wash-strong"
        disabled={!data}
      >
        {data ? (
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand/20 text-sm font-bold text-brand">
            {initial}
          </span>
        ) : (
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-wash">
            <Loader2 className="h-4 w-4 animate-spin text-muted" />
          </span>
        )}
        <ChevronDown
          className={`hidden h-3.5 w-3.5 text-muted transition sm:block ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && data ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 z-50 mt-2 w-[19rem] origin-top-right animate-rise rounded-xl border border-line bg-raised p-3 shadow-card"
        >
          <div className="flex items-center gap-3 px-1">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand/20 text-lg font-bold text-brand">
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-fg" title={data.email}>
                {data.email}
              </p>
              <p className="text-[11px] text-subtle">
                {data.isAdmin
                  ? 'Administrator'
                  : data.localhost
                    ? 'Local development'
                    : 'Member'}
              </p>
            </div>
          </div>

          <div className="mt-3 rounded-lg border border-line bg-wash p-2.5">
            {data.isAdmin ? (
              <span className="flex items-center justify-center gap-1.5 rounded-md border border-warn/60 bg-warn/10 px-3 py-2 text-xs font-bold text-warn">
                <Crown className="h-3.5 w-3.5" />
                Admin (Unlimited Credits)
              </span>
            ) : (
              <div className="flex items-center justify-between gap-2">
                <span className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-bold text-fg">
                  {data.credits} Credit{data.credits === 1 ? '' : 's'} Left
                </span>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => alert('Coming Soon')}
                >
                  Buy Credits
                </button>
              </div>
            )}
          </div>

          {data.localhost ? (
            <p className="mt-2.5 px-1 text-[10px] leading-relaxed text-subtle">
              Running on localhost — login is bypassed here.
            </p>
          ) : (
            <>
              <div className="my-2 h-px bg-line" />
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  signOut({ callbackUrl: '/' });
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-muted transition hover:bg-wash-strong hover:text-fg"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
