"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button } from "@/components/ui";
import { api, ApiError, type Finding, type Validation } from "@/lib/api";

import type { WorkspaceProps } from "./context";

const TONE = { green: "ok", yellow: "warn", red: "bad" } as const;

export function ValidationTab({ version, onGoTo }: WorkspaceProps & { onGoTo: (tab: string) => void }) {
  const vid = version.version.id;
  const [report, setReport] = useState<Validation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Validation>(`/versions/${vid}/validation`)
      .then((r) => !cancelled && setReport(r))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not run the checks."));
    return () => {
      cancelled = true;
    };
  }, [vid, version, run]);

  if (error) return <Alert>{error}</Alert>;
  if (!report) return <p className="text-muted">Running checks…</p>;

  const reds = report.findings.filter((f) => f.severity === "red");
  const yellows = report.findings.filter((f) => f.severity === "yellow");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Alert tone={TONE[report.status]}>
          <strong>{report.status === "green" ? "✓ " : ""}{report.message}</strong>
          {report.status === "green" ? (
            <span className="block text-xs">
              Arithmetic, units and consistency are correct. This does not confirm the engineering quantities; verify them.
            </span>
          ) : null}
        </Alert>
        <Button variant="secondary" onClick={() => setRun((n) => n + 1)}>
          Run checks again
        </Button>
      </div>
      <Group title="Errors" tone="bad" findings={reds} onGoTo={onGoTo} />
      <Group title="Review" tone="warn" findings={yellows} onGoTo={onGoTo} />
      <p className="text-xs text-muted">
        Every measurement line is recalculated from its inputs for these checks. Nothing is changed by running them.
      </p>
    </div>
  );
}

function Group({ title, tone, findings, onGoTo }: { title: string; tone: "bad" | "warn"; findings: Finding[]; onGoTo: (tab: string) => void }) {
  if (!findings.length) return null;
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 font-semibold">
        {title} <Badge tone={tone === "bad" ? "neutral" : "warn"}>{findings.length}</Badge>
      </h2>
      <ul className="divide-y divide-line rounded border border-line">
        {findings.map((f, i) => (
          <li key={`${f.rule_id}-${f.entity_id ?? i}-${i}`} className="flex flex-wrap items-start gap-3 px-3 py-2">
            <span className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${tone === "bad" ? "bg-bad" : "bg-warn"}`} aria-hidden />
            <span className="flex-1">{f.message}</span>
            <code className="text-[11px] text-muted">{f.rule_id}</code>
            {f.entity_type ? (
              <button
                className="text-xs text-accent hover:underline"
                onClick={() => onGoTo(f.entity_type === "measurement" ? "detailed" : f.entity_type === "parameter" ? "parameters" : "boq")}
              >
                Open
              </button>
            ) : f.rule_id.startsWith("GST") ? (
              <button className="text-xs text-accent hover:underline" onClick={() => onGoTo("abstract")}>
                Open
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
