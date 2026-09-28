import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppSidebar } from "@/components/AppSidebar";
import { Brand, SsrPill } from "@/components/Brand";
import { Disclaimer } from "@/components/Disclaimer";
import { SessionProvider } from "@/components/Session";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UserMenu, VerifyEmailBanner } from "@/components/TopBar";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Cheap server-side redirect for signed-out visitors. This is not the security
  // boundary: every API call is authenticated by the backend.
  if (!(await cookies()).get("eai_session")) redirect("/login");

  return (
    <SessionProvider>
      <div className="flex min-h-screen flex-col">
        <header className="no-print flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-5 py-3">
          <Brand />
          <div className="flex flex-wrap items-center gap-2">
            <SsrPill />
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <VerifyEmailBanner />
        <div className="flex min-w-0 flex-1 flex-col md:flex-row">
          <AppSidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <main className="flex-1 p-4 md:p-6">{children}</main>
            <Disclaimer />
          </div>
        </div>
      </div>
    </SessionProvider>
  );
}
