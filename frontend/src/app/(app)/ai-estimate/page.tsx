import { Suspense } from "react";

import { AiEstimate } from "./AiEstimate";

export const metadata = { title: "AI Estimate" };

export default function AiEstimatePage() {
  return (
    <Suspense>
      <AiEstimate />
    </Suspense>
  );
}
