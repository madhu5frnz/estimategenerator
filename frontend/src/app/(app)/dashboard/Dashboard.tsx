"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert, ButtonLink, Card, StatusBadge } from "@/components/ui";
import { api, ApiError, type Dashboard as DashboardData } from "@/lib/api";
import { indianDate, inr } from "@/lib/format";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border border-line p-4">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className="num mt-1 text-lg font-semibold [overflow-wrap:anywhere] sm:text-2xl">{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

function limitText(used: number, limit: unknown): string {
  return limit === null || limit === undefined ? `${used} (no limit)` : `${used} of ${String(limit)}`;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<DashboardData>("/dashboard/summary")
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the dashboard."));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="text-muted">Loading…</p>;

  const limits = data.subscription.limits as Record<string, number | null>;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/projects/new">New project</ButtonLink>
          <ButtonLink href="/ai-estimate" variant="secondary">
            AI Estimate
          </ButtonLink>
          <ButtonLink href="/calculator" variant="secondary">
            Quantity calculator
          </ButtonLink>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Projects" value={String(data.total_projects)} />
        <Tile label="Drafts" value={String(data.draft_projects)} hint={`${data.in_progress_projects} in progress`} />
        <Tile label="Completed" value={String(data.completed_projects)} />
        <Tile label="Estimated value" value={inr(data.total_estimated_value)} hint="Sum of project estimated values" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card
          title="Recent projects"
          className="lg:col-span-2"
          actions={
            <Link href="/projects" className="text-xs text-accent hover:underline">
              All projects
            </Link>
          }
        >
          {data.recent_projects.length === 0 ? (
            <div className="py-6 text-center text-muted">
              <p>No projects yet.</p>
              <ButtonLink href="/projects/new" className="mt-3">
                Create your first project
              </ButtonLink>
            </div>
          ) : (
            <table className="w-full text-left">
              <thead className="text-xs text-muted uppercase">
                <tr>
                  <th className="pr-3 pb-2">Project</th>
                  <th className="pr-3 pb-2">Type</th>
                  <th className="pr-3 pb-2 text-right">Est. value</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_projects.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-2 pr-3">
                      <Link href={`/projects/${p.id}`} className="font-medium text-accent hover:underline">
                        {p.name}
                      </Link>
                      <div className="text-xs text-muted">Updated {indianDate(p.updated_at)}</div>
                    </td>
                    <td className="py-2 pr-3">{p.project_type_label}</td>
                    <td className="num py-2 pr-3 text-right">{inr(p.estimated_value)}</td>
                    <td className="py-2">
                      <StatusBadge status={p.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Plan">
          <dl className="space-y-2">
            <div className="flex justify-between">
              <dt className="text-muted">Plan</dt>
              <dd className="font-medium">{data.subscription.plan_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Projects</dt>
              <dd className="num">{limitText(data.usage.projects, limits.projects)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">AI generations</dt>
              <dd className="num">{limitText(data.usage.ai_generations, limits.ai_generations_per_period)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Renews</dt>
              <dd>{indianDate(data.subscription.current_period_end)}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted">Recent estimates and documents appear here from M3.</p>
        </Card>
      </div>
    </div>
  );
}
