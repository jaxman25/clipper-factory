import Link from 'next/link';

export default function TopBar({ active = 'dashboard', health = null }) {
  const queue = health?.queue;
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        <span className="brand-mark">◈</span>
        <span>
          African Clipper Factory
          <small>Shorts autopilot · EAT</small>
        </span>
      </Link>
      <nav className="nav">
        <Link href="/" className={active === 'dashboard' ? 'active' : ''}>
          Dashboard
        </Link>
        <Link href="/settings" className={active === 'settings' ? 'active' : ''}>
          Settings
        </Link>
      </nav>
      <div className="header-meta">
        <span className="status-pill">
          <span className={`dot ${health?.status === 'ok' ? '' : 'offline'}`} />
          {health?.status === 'ok' ? 'Online' : 'Checking…'}
        </span>
        {typeof queue === 'number' && <span>{queue} in queue</span>}
      </div>
    </header>
  );
}
