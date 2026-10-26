'use client';

import { useCallback, useEffect, useState } from 'react';
import { Activity, Loader2, RotateCcw, Trash2 } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useStudio } from '@/components/studio/StudioProvider';

/** Fired on `window` after a successful DELETE /api/logs. */
const LOGS_CLEARED_EVENT = 'clipper:logs-cleared';
/** Fired on `window` by an ActivityFeed whenever its log state changes. */
const LOGS_STATE_EVENT = 'clipper:logs-state';
/** Fired on `window` after a successful POST /api/logs (refetch only). */
const LOGS_REFRESH_EVENT = 'clipper:logs-refresh';

// Level dots follow the UI palette instead of Tailwind's default hues, so the
// feed keeps its warm tone in both themes (no stray blues).
const TONE = {
  info: 'bg-brand/80',
  warn: 'bg-warn/90',
  error: 'bg-danger/90',
};

export function ClearLogsButton() {
  const [busy, setBusy] = useState(false);
  const [hasLogs, setHasLogs] = useState(false);
  const { notify } = useStudio();

  // The panel lives in the card body, so the feed tells us over the window
  // whether there is anything to clear. Hidden until it says otherwise.
  useEffect(() => {
    function onLogsState(event) {
      setHasLogs(Boolean(event.detail?.hasLogs));
    }
    window.addEventListener(LOGS_STATE_EVENT, onLogsState);
    return () => window.removeEventListener(LOGS_STATE_EVENT, onLogsState);
  }, []);

  async function handleClear() {
    if (!window.confirm('Are you sure you want to clear all logs?')) return;
    setBusy(true);
    try {
      const response = await fetch('/api/logs', { method: 'DELETE' });
      if (response.ok) {
        // Every mounted ActivityFeed hears this and refetches, so all panels
        // blank out at once without a page reload.
        window.dispatchEvent(new Event(LOGS_CLEARED_EVENT));
        notify('Logs cleared');
      } else if (response.status === 401) {
        notify('Sign in to the dashboard to clear logs');
      } else {
        notify('Could not clear logs');
      }
    } catch (err) {
      notify('Could not clear logs');
    } finally {
      setBusy(false);
    }
  }

  if (!hasLogs) return null;

  return (
    <button
      type="button"
      onClick={handleClear}
      disabled={busy}
      title="Clear logs"
      aria-label="Clear logs"
      className="btn btn-ghost btn-sm"
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Trash2 className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

export function RestoreLogsButton() {
  const [busy, setBusy] = useState(false);
  const [hasLogs, setHasLogs] = useState(false);
  const { notify } = useStudio();

  // Mirror of ClearLogsButton: the feed reports its state, so the header only
  // ever offers the one action that makes sense right now.
  useEffect(() => {
    function onLogsState(event) {
      setHasLogs(Boolean(event.detail?.hasLogs));
    }
    window.addEventListener(LOGS_STATE_EVENT, onLogsState);
    return () => window.removeEventListener(LOGS_STATE_EVENT, onLogsState);
  }, []);

  async function handleRestore() {
    setBusy(true);
    try {
      const response = await fetch('/api/logs', { method: 'POST' });
      if (response.ok) {
        // Refetch without blanking the panel first, so the seeded entries
        // appear as soon as the request lands.
        window.dispatchEvent(new Event(LOGS_REFRESH_EVENT));
        notify('Sample logs restored');
      } else if (response.status === 401) {
        notify('Sign in to the dashboard to restore logs');
      } else {
        notify('Could not restore sample logs');
      }
    } catch (err) {
      notify('Could not restore sample logs');
    } finally {
      setBusy(false);
    }
  }

  if (hasLogs) return null;

  return (
    <button
      type="button"
      onClick={handleRestore}
      disabled={busy}
      title="Restore sample logs"
      aria-label="Restore sample logs"
      className="btn btn-ghost btn-sm"
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <RotateCcw className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

export default function ActivityFeed({ limit = 8, pollMs = 15000 }) {
  const [logs, setLogs] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/logs?limit=40', { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      const entries = payload.logs || [];
      setLogs(entries);
      window.dispatchEvent(new CustomEvent(LOGS_STATE_EVENT, { detail: { hasLogs: entries.length > 0 } }));
    } catch (err) {
      /* ignore transient log errors */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, pollMs);
    return () => clearInterval(timer);
  }, [load, pollMs]);

  useEffect(() => {
    function onLogsCleared() {
      setLogs([]);
      window.dispatchEvent(new CustomEvent(LOGS_STATE_EVENT, { detail: { hasLogs: false } }));
      load();
    }
    function onLogsRefresh() {
      load();
    }
    window.addEventListener(LOGS_CLEARED_EVENT, onLogsCleared);
    window.addEventListener(LOGS_REFRESH_EVENT, onLogsRefresh);
    return () => {
      window.removeEventListener(LOGS_CLEARED_EVENT, onLogsCleared);
      window.removeEventListener(LOGS_REFRESH_EVENT, onLogsRefresh);
    };
  }, [load]);

  if (!loaded) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-9 animate-shimmer rounded-lg bg-[linear-gradient(90deg,var(--skel),var(--skel-hi),var(--skel))] bg-[length:200%_100%]" />
        ))}
      </div>
    );
  }

  if (!logs.length) {
    return (
      <div className="flex flex-col items-center py-8 text-center">
        <Activity className="h-5 w-5 text-subtle/80" />
        <p className="mt-3 text-xs text-subtle">No activity yet.</p>
      </div>
    );
  }

  return (
    <ul className="-my-1 divide-y divide-line/60">
      {logs.slice(0, limit).map((entry, index) => (
        <li key={`${entry.ts}-${index}`} className="flex gap-3 py-2.5">
          <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', TONE[entry.level] || TONE.info)} />
          <div className="min-w-0">
            <p className="text-[12px] leading-snug text-fg/80">{entry.message}</p>
            <p className="mt-0.5 text-[10px] tabular-nums text-subtle/80">
              {entry.ts
                ? new Date(entry.ts).toLocaleTimeString('en-GB', { hour12: false })
                : '—'}
              {entry.level && entry.level !== 'info' ? ` · ${entry.level}` : ''}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
