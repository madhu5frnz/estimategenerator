import Link from "next/link";

import { ComingSoon } from "@/components/ComingSoon";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <ComingSoon title="Dashboard" milestone="M2 (projects and accounts)">
      <p>
        Available now:{" "}
        <Link href="/calculator" className="text-accent underline">
          Quantity Calculator
        </Link>
        .
      </p>
    </ComingSoon>
  );
}
