import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "EstimateAI", template: "%s · EstimateAI" },
  description: "Estimates, BOQs and quantities for Indian engineers and contractors.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body className="min-h-screen font-sans text-sm antialiased">{children}</body>
    </html>
  );
}
