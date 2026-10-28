'use client';

import { useEffect, useState } from 'react';
import { Crown, Loader2 } from 'lucide-react';

/**
 * Top-right identity pill (spec 04):
 *  - Admin  -> golden "Admin (Unlimited Credits)" badge
 *  - Public -> "X Credits Left" + a Buy Credits button ("Coming Soon")
 *  - Localhost -> treated as admin (login is bypassed there anyway)
 * Re-reads /api/credits whenever the tab regains focus so a spent balance
 * never shows stale after a generation.
 */
export default function UserBadge() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const response = await fetch('/api/credits', { cache: 'no-store' });
        if (!response.ok) {
          if (alive) setFailed(true);
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

  if (failed) return null;
  if (!data) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        …
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs font-medium text-muted sm:inline" title={data.email}>
        {data.email}
      </span>
      {data.isAdmin ? (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/60 bg-warn/10 px-3 py-1.5 text-xs font-bold text-warn shadow-[0_0_12px_rgba(240,190,120,0.25)]">
          <Crown className="h-3.5 w-3.5" />
          Admin (Unlimited Credits)
        </span>
      ) : (
        <>
          <span className="inline-flex items-center rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-bold text-fg">
            {data.credits} Credit{data.credits === 1 ? '' : 's'} Left
          </span>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => alert('Coming Soon')}
          >
            Buy Credits
          </button>
        </>
      )}
    </div>
  );
}
