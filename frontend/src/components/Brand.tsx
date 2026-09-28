import Link from "next/link";

/** Department mark: a water drop, as on I&CAD letterheads. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/dashboard" className="flex items-center gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-surface shadow-sm">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-ink" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M12 2.5c-3.5 4.6-6.5 8.4-6.5 11.8A6.5 6.5 0 0 0 12 20.8a6.5 6.5 0 0 0 6.5-6.5c0-3.4-3-7.2-6.5-11.8Z" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block font-serif text-lg font-bold tracking-wide">TELANGANA I&amp;CAD</span>
        {compact ? null : (
          <span className="block text-[10px] font-medium tracking-[0.18em] text-muted uppercase">
            Irrigation &amp; CAD Department · Estimate Suite 2026-27
          </span>
        )}
      </span>
    </Link>
  );
}

export function SsrPill() {
  return (
    <span className="no-print inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-[11px] font-semibold tracking-[0.12em] uppercase">
      <span className="h-1.5 w-1.5 rounded-full bg-accent-strong" aria-hidden /> Active SSR 2026-27
    </span>
  );
}
