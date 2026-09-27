import Link from "next/link";

import { Disclaimer } from "@/components/Disclaimer";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-panel">
      <main className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center">
        <div className="w-full max-w-sm">
          <Link href="/login" className="mb-6 block text-center text-xl font-semibold">
            EstimateAI
          </Link>
          <div className="rounded border border-line bg-white p-6 shadow-sm">{children}</div>
        </div>
      </main>
      <Disclaimer />
    </div>
  );
}
