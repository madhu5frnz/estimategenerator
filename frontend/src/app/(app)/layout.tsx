import Link from "next/link";

import { Disclaimer } from "@/components/Disclaimer";
import { Sidebar } from "@/components/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-line md:w-56 md:shrink-0 md:border-r">
        <Link href="/dashboard" className="block px-6 pt-5 pb-2 text-base font-semibold">
          EstimateAI
        </Link>
        <Sidebar />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 p-6">{children}</main>
        <Disclaimer />
      </div>
    </div>
  );
}
