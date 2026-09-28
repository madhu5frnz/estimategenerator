import { Brand } from "@/components/Brand";
import { Disclaimer } from "@/components/Disclaimer";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-page">
      <main className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex justify-center">
            <Brand />
          </div>
          <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">{children}</div>
        </div>
      </main>
      <Disclaimer />
    </div>
  );
}
