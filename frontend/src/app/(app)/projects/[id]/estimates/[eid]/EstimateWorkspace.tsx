"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Field, Input } from "@/components/ui";
import { api, ApiError, post, type Estimate, type Template, type Unit, type Version, type VersionSummary } from "@/lib/api";
import { indianDate } from "@/lib/format";

import { BoqTab } from "./BoqTab";
import type { Mutate } from "./context";
import { DataTab } from "./DataTab";
import { DetailedTab } from "./DetailedTab";
import { CertificatesSheet, CheckSlipSheet, CoverSheet, QuotationsSheet } from "./DocketSheets";
import { GeneralAbstractTab } from "./GeneralAbstractTab";
import { LeadTab } from "./LeadTab";
import { ParametersTab } from "./ParametersTab";
import { SeigniorageTab } from "./SeigniorageTab";
import { ValidationTab } from "./ValidationTab";
import { VersionsTab } from "./VersionsTab";

/** The estimate as a departmental docket: the printed sheets in order, then working tools. */
const SHEETS = [
  { key: "cover", no: 1, label: "Cover Page", hint: "Name of work and amount of estimate" },
  { key: "check-slip", no: 2, label: "Check Slip", hint: "Check slip accompanying the estimate" },
  { key: "detailed", no: 3, label: "Detailed Estimate", hint: "Measurements: Nos x L x B x D" },
  { key: "data", no: 4, label: "Data Rate Analysis", hint: "Rate analysis of each item (Standard Data 2026-27)" },
  { key: "general-abstract", no: 5, label: "Abstract & Recap", hint: "Abstract estimate and General Abstract" },
  { key: "lead", no: 6, label: "Lead & Quarry Chart", hint: "Lead statement from the SoR lead table" },
  { key: "seigniorage", no: 7, label: "SMET & Seigniorage", hint: "Seigniorage, DMF, SMET and permit fee" },
  { key: "certificates", no: 8, label: "Certificates", hint: "Statutory certificates accompanying the estimate" },
  { key: "quotations", no: 9, label: "Quotations / Non-SOR", hint: "Items not priced from the SoR" },
] as const;
const TOOLS = [
  { key: "boq", label: "Items (BOQ entry)" },
  { key: "parameters", label: "Parameters" },
  { key: "validation", label: "Validation" },
  { key: "versions", label: "Versions" },
] as const;

type Problem = { message: string; requestId: string | null };

export function EstimateWorkspace({ projectId, estimateId }: { projectId: string; estimateId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = params.get("tab") ?? "boq";
  const requestedVersion = params.get("v");
  const itemParam = params.get("item");

  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [freezing, setFreezing] = useState(false);

  const go = useCallback(
    (changes: { tab?: string; v?: string | null; item?: string }) => {
      const next = new URLSearchParams(params.toString());
      if (changes.tab) next.set("tab", changes.tab);
      if (changes.item) next.set("item", changes.item);
      if (changes.v === null) next.delete("v");
      else if (changes.v) next.set("v", changes.v);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  const refreshVersions = useCallback(
    () => api<VersionSummary[]>(`/estimates/${estimateId}/versions`).then(setVersions),
    [estimateId],
  );

  useEffect(() => {
    Promise.all([api<Unit[]>("/units"), api<Template[]>("/calculation-templates")])
      .then(([u, t]) => {
        setUnits(u);
        setTemplates(t);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<Estimate>(`/estimates/${estimateId}`)
      .then(async (e) => {
        const v = await api<Version>(`/versions/${requestedVersion ?? e.draft_version_id}`);
        const list = await api<VersionSummary[]>(`/estimates/${estimateId}/versions`);
        if (cancelled) return;
        setEstimate(e);
        setVersion(v);
        setVersions(list);
      })
      .catch((e: unknown) => !cancelled && setLoadError(e instanceof ApiError ? e.message : "Could not load the estimate."));
    return () => {
      cancelled = true;
    };
  }, [estimateId, requestedVersion]);

  const mutate: Mutate = useCallback(
    async (request) => {
      setProblem(null);
      setNotice(null);
      try {
        const next = await request();
        setVersion(next);
        setNotice(next.notice ?? null);
        return next;
      } catch (e) {
        setProblem(
          e instanceof ApiError
            ? { message: e.message, requestId: e.requestId }
            : { message: "The change could not be saved.", requestId: null },
        );
        throw e;
      }
    },
    [],
  );

  if (loadError) return <Alert>{loadError}</Alert>;
  if (!estimate || !version) return <p className="text-muted">Loading…</p>;

  const frozen = version.version.status === "frozen";
  const draft = versions.find((v) => v.status === "draft");
  const props = { version, mutate, units, templates, editable: version.can_edit };

  const sheet = SHEETS.find((x) => x.key === tab);
  const tool = TOOLS.find((x) => x.key === tab);

  return (
    <div className="-m-4 flex min-h-full flex-col md:-m-6 md:flex-row">
      <aside className="no-print border-b border-line bg-panel md:w-64 md:shrink-0 md:border-r md:border-b-0">
        <div className="p-4">
          <Link href={`/projects/${projectId}`} className="text-xs text-muted hover:text-ink">
            ← {version.estimate.project_name}
          </Link>
          <div className="mt-4 text-[10px] font-semibold tracking-[0.18em] text-muted uppercase">Departmental docket (9 sheets)</div>
        </div>
        <nav aria-label="Docket sheets" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
          {SHEETS.map((x) => (
            <DocketLink key={x.key} active={tab === x.key} onClick={() => go({ tab: x.key })} no={x.no} label={x.label} sub={x.key.replace("-", " ")} />
          ))}
          <div className="mt-3 hidden px-3 text-[10px] font-semibold tracking-[0.18em] text-muted uppercase md:block">Working</div>
          {TOOLS.map((x) => (
            <DocketLink key={x.key} active={tab === x.key} onClick={() => go({ tab: x.key })} label={x.label} />
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1 space-y-4 p-4 md:p-6">
        <div className="no-print flex flex-wrap items-start justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3 shadow-sm">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold tracking-wide uppercase">{version.estimate.project_name}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-medium text-accent">
                {version.estimate.title} · {version.estimate.estimate_number}
              </span>
              <Badge tone={frozen ? "neutral" : "accent"}>
                V{version.version.version_no} · {frozen ? "Saved (read-only)" : "Draft"}
              </Badge>
              {frozen && version.version.change_note ? <span className="text-muted">“{version.version.change_note}”</span> : null}
              {frozen && version.version.frozen_at ? (
                <span className="text-muted">
                  saved {indianDate(version.version.frozen_at)} by {version.version.frozen_by_name ?? "—"}
                </span>
              ) : null}
              {!version.can_edit && !frozen ? <Badge>Your role ({version.my_role}) is read-only</Badge> : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              id="version-select"
              aria-label="Version"
              value={version.version.id}
              onChange={(e) => go({ v: e.target.value === draft?.id ? null : e.target.value })}
              className="rounded-full border border-line bg-surface px-3 py-1.5 text-xs"
            >
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  V{v.version_no} {v.status === "draft" ? "(draft)" : `— ${v.change_note ?? "saved"}`}
                </option>
              ))}
            </select>
            {version.can_edit ? (
              <Button variant="secondary" className="rounded-full px-3 py-1.5 text-xs" onClick={() => setFreezing(true)}>
                Save as version…
              </Button>
            ) : null}
            <Button className="rounded-full px-3 py-1.5 text-xs" onClick={() => window.print()}>
              Print sheet
            </Button>
          </div>
        </div>

        {frozen && draft ? (
          <Alert tone="info">
            You are viewing a saved version. Changes are made in the current draft.{" "}
            <button className="underline" onClick={() => go({ v: null })}>
              Open V{draft.version_no} (draft)
            </button>
          </Alert>
        ) : null}
        {notice ? <Alert tone="ok">{notice}</Alert> : null}
        {problem ? (
          <Alert>
            {problem.message}
            {problem.requestId ? <span className="block text-xs opacity-70">Request id: {problem.requestId}</span> : null}
          </Alert>
        ) : null}

        {sheet ? (
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-ink font-semibold text-page">{sheet.no}</span>
            <div>
              <h1 className="font-serif text-2xl font-bold">{sheet.label}</h1>
              <p className="text-xs text-muted">{sheet.hint}</p>
            </div>
          </div>
        ) : (
          <h1 className="font-serif text-2xl font-bold">{tool?.label ?? "Items (BOQ entry)"}</h1>
        )}

        {tab === "cover" ? <CoverSheet {...props} /> : null}
        {tab === "check-slip" ? <CheckSlipSheet {...props} /> : null}
        {tab === "certificates" ? <CertificatesSheet {...props} /> : null}
        {tab === "quotations" ? <QuotationsSheet {...props} /> : null}
      {tab === "boq" ? (
        <BoqTab {...props} onShowLines={() => go({ tab: "detailed" })} onShowData={(item) => go({ tab: "data", item })} />
      ) : null}
      {tab === "data" ? <DataTab {...props} itemId={itemParam} onPickItem={(item) => go({ item })} /> : null}
      {tab === "lead" ? <LeadTab {...props} /> : null}
      {tab === "seigniorage" ? <SeigniorageTab {...props} /> : null}
      {tab === "general-abstract" ? <GeneralAbstractTab {...props} onOpenData={(item) => go({ tab: "data", item })} /> : null}
      {tab === "detailed" ? <DetailedTab {...props} /> : null}
      {tab === "parameters" ? <ParametersTab {...props} /> : null}
      {tab === "validation" ? <ValidationTab {...props} onGoTo={(t) => go({ tab: t })} /> : null}
      {tab === "versions" ? (
        <VersionsTab
          versions={versions}
          currentId={version.version.id}
          onOpen={(id) => go({ v: id === draft?.id ? null : id, tab: "boq" })}
        />
      ) : null}
      </div>

      {freezing ? (
        <FreezeDialog
          versionNo={version.version.version_no}
          onClose={() => setFreezing(false)}
          onFreeze={async (note) => {
            await mutate(() => post<Version>(`/versions/${version.version.id}/freeze`, { change_note: note }));
            setFreezing(false);
            await refreshVersions();
            go({ v: null });
          }}
        />
      ) : null}
    </div>
  );
}

function FreezeDialog({ versionNo, onClose, onFreeze }: { versionNo: number; onClose: () => void; onFreeze: (note: string) => Promise<void> }) {
  const [note, setNote] = useState(versionNo === 1 ? "Initial estimate" : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title={`Save V${versionNo} as a version`} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await onFreeze(note);
          } catch (err) {
            setError(err instanceof ApiError ? err.message : "Could not save the version.");
            setBusy(false);
          }
        }}
      >
        {error ? <Alert>{error}</Alert> : null}
        <p className="text-muted">
          V{versionNo} will become read-only, exactly as it is now. You continue editing in V{versionNo + 1}.
        </p>
        <Field label="What changed in this version?" required hint="e.g. Width changed from 5 m to 5.5 m">
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} autoFocus />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !note.trim()}>
            Save V{versionNo}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function DocketLink({ active, onClick, no, label, sub }: { active: boolean; onClick: () => void; no?: number; label: string; sub?: string }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`flex shrink-0 items-center gap-3 rounded-lg border px-3 py-2 text-left ${
        active ? "border-accent-strong/70 bg-surface shadow-sm" : "border-transparent hover:bg-surface"
      }`}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold whitespace-nowrap">{label}</span>
        {sub ? <span className="block text-[10px] text-muted uppercase">{sub}</span> : null}
      </span>
      {no ? (
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-semibold ${
            active ? "bg-accent-strong text-[#2b1d05]" : "border border-line text-muted"
          }`}
        >
          {no}
        </span>
      ) : null}
    </button>
  );
}
