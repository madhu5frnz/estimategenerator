import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Disclaimer } from "@/components/Disclaimer";
import { SessionProvider } from "@/components/Session";
import { Sidebar } from "@/components/Sidebar";
import { TopBar, VerifyEmailBanner } from "@/components/TopBar";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Cheap server-side redirect for signed-out visitors. This is not the security
  // boundary: every API call is authenticated by the backend.
  if (!(await cookies()).get("eai_session")) redirect("/login");

  return (
    <SessionProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <aside className="border-b border-line md:w-56 md:shrink-0 md:border-r md:border-b-0">
          <Link href="/dashboard" className="block px-6 pt-4 pb-2 text-base font-semibold md:pt-5">
            EstimateAI
          </Link>
          <Sidebar />
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <VerifyEmailBanner />
          <main className="flex-1 p-6">{children}</main>
          <Disclaimer />
        </div>
      </div>
    </SessionProvider>
  );
}
