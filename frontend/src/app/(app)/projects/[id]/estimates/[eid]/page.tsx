import { Suspense } from "react";

import { EstimateWorkspace } from "./EstimateWorkspace";

export const metadata = { title: "Estimate" };

export default async function EstimatePage({ params }: { params: Promise<{ id: string; eid: string }> }) {
  const { id, eid } = await params;
  return (
    <Suspense>
      <EstimateWorkspace projectId={id} estimateId={eid} />
    </Suspense>
  );
}
