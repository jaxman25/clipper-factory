import { cn } from '@/lib/cn';

export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="label text-brand">{eyebrow}</p>}
        <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, icon: Icon, tone = 'default' }) {
  return (
    <div className="card p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-subtle">{label}</p>
        {Icon && (
          <Icon
            className={cn('h-4 w-4', tone === 'brand' ? 'text-brand' : 'text-subtle/80')}
            aria-hidden="true"
          />
        )}
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-subtle">{hint}</p>}
    </div>
  );
}

export function SectionCard({ title, description, actions, children, className }) {
  return (
    <section className={cn('card', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line/60 px-5 py-4 sm:px-6">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-tight">{title}</h2>}
            {description && <p className="mt-1 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-5 sm:p-6">{children}</div>
    </section>
  );
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-14 text-center">
      {Icon && (
        <span className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-full bg-wash text-subtle">
          <Icon className="h-5 w-5" />
        </span>
      )}
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }) {
  return (
    <div
      className={cn(
        'animate-shimmer rounded-xl border border-line/60 bg-[linear-gradient(90deg,var(--skel),var(--skel-hi),var(--skel))] bg-[length:200%_100%]',
        className
      )}
    />
  );
}

/** Small binary toggle (On/Off) for boolean settings.
 *
 * Controlled: the parent owns `value`; `onChange` fires whenever the user
 * flips it. On its own it does not persist anything - callers that want
 * localStorage/session persistence should keep their own state and write it
 * on `onChange`.
 */
export function Switch({
  checked,
  onChange,
  disabled = false,
  className,
  id,
  label,
}) {
  const handleClick = () => {
    if (disabled) return;
    onChange(!checked);
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-3 cursor-pointer select-none rounded-lg border border-line/70 bg-wash px-4 py-2 text-sm font-medium text-fg/90 transition hover:bg-wash-strong hover:text-fg',
        disabled && 'pointer-events-none opacity-50',
        className
      )}
    >
      <span
        className={cn(
          'relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors duration-150',
          checked ? 'bg-brand' : 'bg-wash-strong'
        )}
        role="switch"
        aria-checked={checked}
        aria-label={label || undefined}
        tabIndex={disabled ? -1 : 0}
        onClick={handleClick}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleClick();
          }
        }}
      >
        <span
          className={cn(
            'pointer-events-none absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-150',
            checked ? 'translate-x-5' : 'translate-x-0'
          )}
        />
      </span>
      {label != null && <span className="shrink-0">{label}</span>}
    </span>
  );
}
