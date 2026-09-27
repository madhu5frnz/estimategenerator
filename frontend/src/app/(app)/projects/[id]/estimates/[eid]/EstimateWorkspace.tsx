"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Field, Input } from "@/components/ui";
import { api, ApiError, post, type Estimate, type Template, type Unit, type Version, type VersionSummary } from "@/lib/api";
import { indianDate } from "@/lib/format";

import { AbstractTab } from "./AbstractTab";
import { BoqTab } from "./BoqTab";
import type { Mutate } from "./context";
import { DetailedTab } from "./DetailedTab";
import { ParametersTab } from "./ParametersTab";
import { ValidationTab } from "./ValidationTab";
import { VersionsTab } from "./VersionsTab";

const TABS = [
  { key: "boq", label: "BOQ" },
  { key: "detailed", label: "Detailed estimate" },
  { key: "parameters", label: "Parameters" },
  { key: "abstract", label: "Abstract" },
  { key: "validation", label: "Validation" },
  { key: "versions", label: "Versions" },
] as const;
const LATER = [{ label: "Export", milestone: "M6" }];

type Problem = { message: string; requestId: string | null };

export function EstimateWorkspace({ projectId, estimateId }: { projectId: string; estimateId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = (params.get("tab") ?? "boq") as (typeof TABS)[number]["key"];
  const requestedVersion = params.get("v");

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
    (changes: { tab?: string; v?: string | null }) => {
      const next = new URLSearchParams(params.toString());
      if (changes.tab) next.set("tab", changes.tab);
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

  return (
    <div className="space-y-4">
      <div className="text-xs">
        <Link href="/projects" className="text-accent hover:underline">
          Projects
        </Link>{" "}
        /{" "}
        <Link href={`/projects/${projectId}`} className="text-accent hover:underline">
          {version.estimate.project_name}
        </Link>{" "}
        / {version.estimate.estimate_number}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            {version.estimate.title} <span className="text-base font-normal text-muted">{version.estimate.estimate_number}</span>
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={frozen ? "neutral" : "accent"}>
              V{version.version.version_no} · {frozen ? "Frozen (read-only)" : "Draft"}
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
          <label className="text-xs text-muted" htmlFor="version-select">
            Version
          </label>
          <select
            id="version-select"
            value={version.version.id}
            onChange={(e) => go({ v: e.target.value === draft?.id ? null : e.target.value })}
            className="rounded border border-line bg-white px-2 py-1.5"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                V{v.version_no} {v.status === "draft" ? "(draft)" : `— ${v.change_note ?? "frozen"}`}
              </option>
            ))}
          </select>
          {version.can_edit ? (
            <Button variant="secondary" onClick={() => setFreezing(true)}>
              Save as version…
            </Button>
          ) : null}
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

      <nav aria-label="Estimate sections" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => go({ tab: t.key })}
            aria-current={tab === t.key ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 ${tab === t.key ? "border-accent font-medium text-accent" : "border-transparent text-ink hover:text-accent"}`}
          >
            {t.label}
          </button>
        ))}
        {LATER.map((t) => (
          <span key={t.label} title={`Arrives in ${t.milestone}`} className="px-3 py-2 text-muted/70">
            {t.label} <span className="text-[10px]">({t.milestone})</span>
          </span>
        ))}
      </nav>

      {tab === "boq" ? <BoqTab {...props} onShowLines={() => go({ tab: "detailed" })} /> : null}
      {tab === "detailed" ? <DetailedTab {...props} /> : null}
      {tab === "parameters" ? <ParametersTab {...props} /> : null}
      {tab === "abstract" ? <AbstractTab {...props} /> : null}
      {tab === "validation" ? <ValidationTab {...props} onGoTo={(t) => go({ tab: t })} /> : null}
      {tab === "versions" ? (
        <VersionsTab
          versions={versions}
          currentId={version.version.id}
          onOpen={(id) => go({ v: id === draft?.id ? null : id, tab: "boq" })}
        />
      ) : null}

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
