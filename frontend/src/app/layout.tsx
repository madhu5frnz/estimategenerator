import type { Metadata } from "next";

import { THEME_SCRIPT } from "@/components/ThemeToggle";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Telangana I&CAD Estimate Suite", template: "%s · I&CAD Estimate Suite" },
  description: "Estimates in the Telangana I&CAD format: Standard Data 2026-27, data sheets, lead statement, seigniorage and General Abstract.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" suppressHydrationWarning>
      <head>
        {/* Fixed string: sets the saved theme before the first paint. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-page font-sans text-sm text-ink antialiased">{children}</body>
    </html>
  );
}
