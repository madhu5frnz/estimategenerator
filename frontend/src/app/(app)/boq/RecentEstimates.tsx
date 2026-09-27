"use client";

import { useEffect, useState } from "react";

import { EstimateList } from "@/components/EstimateList";
import { Alert, ButtonLink, Card } from "@/components/ui";
import { api, ApiError, type Estimate } from "@/lib/api";

export function RecentEstimates() {
  const [estimates, setEstimates] = useState<Estimate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Estimate[]>("/estimates?limit=50")
      .then(setEstimates)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load estimates."));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">BOQ</h1>
      <p className="text-muted">Open an estimate to edit its BOQ. Estimates are created from a project.</p>
      {error ? <Alert>{error}</Alert> : null}
      <Card title="Recent estimates">
        {estimates === null ? (
          <p className="text-muted">Loading…</p>
        ) : estimates.length ? (
          <EstimateList estimates={estimates} showProject />
        ) : (
          <div className="py-4 text-center text-muted">
            <p>No estimates yet.</p>
            <ButtonLink href="/projects" className="mt-3">
              Go to projects
            </ButtonLink>
          </div>
        )}
      </Card>
    </div>
  );
}
