"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
  { href: "/ai-estimate", label: "AI Estimate" },
  { href: "/boq", label: "BOQ" },
  { href: "/rates", label: "Rate Database" },
  { href: "/documents", label: "Documents" },
  { href: "/calculator", label: "Calculator" },
  { href: "/reports", label: "Reports" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 p-3">
      {NAV.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={
              "rounded px-3 py-2 " +
              (active
                ? "bg-accent-soft font-medium text-accent"
                : "text-ink hover:bg-panel")
            }
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
