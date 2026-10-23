'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Bot,
  CalendarClock,
  LayoutDashboard,
  Menu,
  Settings2,
  Sparkles,
  X,
} from 'lucide-react';
import { useStudio } from '@/components/studio/StudioProvider';
import { cn } from '@/lib/cn';

const NAV = [
  { href: '/dashboard', label: 'Dashboard', sub: 'Overview', icon: LayoutDashboard, exact: true },
  { href: '/dashboard/generate', label: 'Generate Clips', sub: 'New clip run', icon: Sparkles },
  { href: '/dashboard/queue', label: 'Queue & Schedule', sub: 'Calendar and clips', icon: CalendarClock },
  { href: '/dashboard/settings', label: 'Auto-Post Settings', sub: 'Slots and tokens', icon: Settings2 },
  { href: '/dashboard/bot', label: 'Bot Control', sub: 'Telegram', icon: Bot },
];

function isActive(pathname, item) {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function Brand() {
  return (
    <Link href="/dashboard" aria-label="Clipper Factory" className="inline-flex items-center">
      <img
        src="/assets/logos/icon-1024.png"
        alt="Clipper Factory"
        width={36}
        height={36}
        className="h-9 w-9"
      />
    </Link>
  );
}

function StatusFooter() {
  const { health, clips } = useStudio();
  const online = health?.status === 'ok';
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () =>
      setClock(
        new Intl.DateTimeFormat('en-GB', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
          timeZone: health?.timezone || 'Africa/Nairobi',
        }).format(new Date())
      );
    tick();
    const timer = setInterval(tick, 30000);
    return () => clearInterval(timer);
  }, [health?.timezone]);

  return (
    <div className="mt-auto p-3">
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-2 text-xs font-medium text-zinc-300">
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                online ? 'bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.15)]' : 'bg-amber-400'
              )}
            />
            Render: {online ? 'Online' : 'Waking…'}
          </span>
          <span className="text-[11px] tabular-nums text-zinc-500">{clock}</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-500">
          <span>{clips.length} in queue</span>
          <span>{health?.posting_times?.join(' · ') || '19:00 · 21:00'}</span>
        </div>
      </div>
    </div>
  );
}

function NavList({ pathname }) {
  return (
    <nav className="space-y-1 px-3">
      {NAV.map((item) => {
        const active = isActive(pathname, item);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition',
              active
                ? 'bg-white/[0.07] font-semibold text-white'
                : 'font-medium text-muted hover:bg-white/[0.04] hover:text-white'
            )}
          >
            <Icon
              className={cn(
                'h-4 w-4 shrink-0 transition',
                active ? 'text-brand' : 'text-zinc-500 group-hover:text-zinc-300'
              )}
            />
            <span className="flex-1 truncate">{item.label}</span>
            {active && <span className="h-1.5 w-1.5 rounded-full bg-brand" />}
          </Link>
        );
      })}
    </nav>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { health } = useStudio();

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  return (
    <>
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-white/10 bg-ink/90 px-4 backdrop-blur lg:hidden">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
          aria-expanded={open}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 transition hover:bg-white/5"
        >
          <Menu className="h-4 w-4" />
        </button>
        <Brand />
        <span className="inline-flex items-center gap-1.5 text-[11px] text-zinc-500">
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              health?.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'
            )}
          />
          {health?.status === 'ok' ? 'Online' : 'Waking'}
        </span>
      </header>

      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[264px] flex-col border-r border-white/10 bg-[#0C0C0E] lg:flex">
        <div className="flex h-16 items-center px-5">
          <Brand />
        </div>
        <p className="px-6 pb-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-600">
          Workspace
        </p>
        <NavList pathname={pathname} />
        <StatusFooter />
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          />
          <div className="absolute inset-y-0 left-0 flex w-[280px] flex-col border-r border-white/10 bg-[#0C0C0E] shadow-2xl">
            <div className="flex h-16 items-center justify-between px-5">
              <Brand />
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="px-6 pb-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-600">
              Workspace
            </p>
            <NavList pathname={pathname} />
            <StatusFooter />
          </div>
        </div>
      )}
    </>
  );
}
