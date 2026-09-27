import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent/90",
  secondary: "border border-line bg-white text-ink hover:bg-panel",
  danger: "bg-bad text-white hover:bg-bad/90",
  ghost: "text-ink hover:bg-panel",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<"button"> & { variant?: ButtonVariant }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded px-4 py-2 font-medium disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  children,
  className = "",
}: {
  href: string;
  variant?: ButtonVariant;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center gap-2 rounded px-4 py-2 font-medium ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Field({
  label,
  error,
  hint,
  required,
  children,
  className = "",
}: {
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block font-medium">
        {label}
        {required ? <span className="text-bad"> *</span> : null}
      </span>
      {children}
      {error ? (
        <span role="alert" className="mt-1 block text-xs text-bad">
          {error}
        </span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-muted">{hint}</span>
      ) : null}
    </label>
  );
}

const INPUT =
  "rounded border border-line bg-white px-3 py-2 disabled:bg-panel disabled:text-muted aria-[invalid=true]:border-bad";

/** Full width unless the caller sets its own width (w-auto, w-36, max-w-sm stays full). */
function inputClass(className?: string): string {
  const custom = className ?? "";
  const hasWidth = /(^|\s)w-/.test(custom);
  return `${INPUT} ${hasWidth ? "" : "w-full"} ${custom}`;
}

export function Input(props: ComponentProps<"input">) {
  return <input {...props} className={inputClass(props.className)} />;
}

export function Select(props: ComponentProps<"select">) {
  return <select {...props} className={inputClass(props.className)} />;
}

export function Textarea(props: ComponentProps<"textarea">) {
  return <textarea {...props} className={inputClass(props.className)} />;
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded border border-line bg-white ${className}`}>
      {title || actions ? (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 className="font-semibold">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Alert({ tone = "bad", children }: { tone?: "bad" | "ok" | "warn" | "info"; children: ReactNode }) {
  const tones = {
    bad: "border-bad/40 bg-red-50 text-bad",
    ok: "border-ok/40 bg-green-50 text-ok",
    warn: "border-warn/40 bg-amber-50 text-warn",
    info: "border-accent/30 bg-accent-soft text-accent",
  };
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`rounded border px-3 py-2 ${tones[tone]}`}>
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" | "ok" | "warn" }) {
  const tones = {
    neutral: "bg-panel text-muted",
    accent: "bg-accent-soft text-accent",
    ok: "bg-green-50 text-ok",
    warn: "bg-amber-50 text-warn",
  };
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "completed" ? "ok" : status === "in_progress" ? "accent" : "neutral";
  const label = { draft: "Draft", in_progress: "In progress", completed: "Completed", archived: "Archived" }[status] ?? status;
  return <Badge tone={tone}>{label}</Badge>;
}
