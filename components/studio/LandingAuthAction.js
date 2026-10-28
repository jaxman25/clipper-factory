'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

/**
 * Top-nav auth slot for the landing page:
 *  - anonymous  -> "Sign in" button linking to /login
 *  - signed in (or on localhost, where login is bypassed) -> avatar + email
 *    profile chip linking to /dashboard
 *
 * Driven by /api/credits, which already knows about sessions and the
 * localhost bypass. While it loads, an invisible button reserves the same
 * space so the header never shifts or flashes the wrong state.
 */
export default function LandingAuthAction() {
  const [data, setData] = useState(null); // null = loading, false = anonymous

  useEffect(() => {
    let alive = true;
    fetch('/api/credits', { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (alive) setData(payload && payload.authenticated ? payload : false);
      })
      .catch(() => {
        if (alive) setData(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (data === null) {
    return (
      <span className="btn btn-sm invisible" aria-hidden="true">
        Sign in
      </span>
    );
  }

  if (!data) {
    return (
      <Link href="/login" className="btn btn-sm">
        Sign in
      </Link>
    );
  }

  const initial = String(data.email || '?').trim().charAt(0).toUpperCase() || '?';
  return (
    <Link
      href="/dashboard"
      className="btn btn-sm"
      title={data.email}
      aria-label={`Open dashboard as ${data.email}`}
    >
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand/20 text-[10px] font-bold text-brand">
        {initial}
      </span>
      <span className="hidden max-w-[140px] truncate sm:inline">{data.email}</span>
      <ArrowRight className="h-3.5 w-3.5" />
    </Link>
  );
}
