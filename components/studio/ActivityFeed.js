'use client';

import { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { cn } from '@/lib/cn';

const TONE = {
  info: 'bg-sky-400/80',
  warn: 'bg-amber-400/90',
  error: 'bg-red-400/90',
};

export default function ActivityFeed({ limit = 8, pollMs = 15000 }) {
  const [logs, setLogs] = useState([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const response = await fetch('/api/logs?limit=40', { cache: 'no-store' });
        if (!response.ok) return;
        const payload = await response.json();
        if (alive) setLogs(payload.logs || []);
      } catch (err) {
        /* ignore transient log errors */
      } finally {
        if (alive) setLoaded(true);
      }
    }
    load();
    const timer = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [pollMs]);

  if (!loaded) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-9 animate-shimmer rounded-lg bg-[linear-gradient(90deg,#121214,#1a1a1d,#121214)] bg-[length:200%_100%]" />
        ))}
      </div>
    );
  }

  if (!logs.length) {
    return (
      <div className="flex flex-col items-center py-8 text-center">
        <Activity className="h-5 w-5 text-zinc-600" />
        <p className="mt-3 text-xs text-zinc-500">No activity yet.</p>
      </div>
    );
  }

  return (
    <ul className="-my-1 divide-y divide-white/5">
      {logs.slice(0, limit).map((entry, index) => (
        <li key={`${entry.ts}-${index}`} className="flex gap-3 py-2.5">
          <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', TONE[entry.level] || TONE.info)} />
          <div className="min-w-0">
            <p className="text-[12px] leading-snug text-zinc-300">{entry.message}</p>
            <p className="mt-0.5 text-[10px] tabular-nums text-zinc-600">
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
