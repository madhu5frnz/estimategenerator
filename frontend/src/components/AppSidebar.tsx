"use client";

import { usePathname } from "next/navigation";

import { Sidebar } from "./Sidebar";

/** The main menu; an open estimate shows its own docket panel instead. */
export function AppSidebar() {
  const pathname = usePathname();
  if (/^\/projects\/[^/]+\/estimates\/[^/]+/.test(pathname)) return null;
  return (
    <aside className="no-print border-b border-line bg-panel md:w-52 md:shrink-0 md:border-r md:border-b-0">
      <Sidebar />
    </aside>
  );
}
