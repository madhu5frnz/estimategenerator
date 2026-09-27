"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Alert, Badge, Button, ButtonLink, Card, Field, Input, Select, Textarea } from "@/components/ui";
import {
  api,
  apiRaw,
  ApiError,
  post,
  type ConfirmResult,
  type Estimate,
  type Extraction,
  type ExtractedComponent,
  type ExtractedParam,
  type Project,
  type SystemInfo,
  type Unit,
} from "@/lib/api";

const EXAMPLES = [
  "Construction of 500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB.",
  "Construction of 2 km CC road, 5.5 m wide, 150 mm thick, including earthwork, GSB and kerbs.",
  "500 మీటర్ల పొడవు, 5.5 మీటర్ల వెడల్పుతో 150 mm మందం CC రోడ్డు నిర్మించాలి.",
  "Compound wall 120 m long, 2.1 m high, 230 mm thick brickwork with plastering on both sides",
];

/** What the user decided for one parameter. */
type Choice = { value: string; unit: string; edited: boolean; confirmed: boolean; acceptDefault: boolean };
type Choices = Record<string, Record<string, Choice>>; // component key → parameter name → choice
type ParamPayload = { accept_default: true } | { value: string; unit: string | null };

function initialChoices(extraction: Extraction): Choices {
  const out: Choices = {};
  for (const c of extraction.components) {
    out[c.key] = {};
    for (const p of c.parameters) {
      out[c.key]![p.name] = { value: p.value ?? "", unit: p.unit ?? "", edited: false, confirmed: false, acceptDefault: false };
    }
  }
  return out;
}

function isResolved(p: ExtractedParam, choice: Choice | undefined): boolean {
  if (!choice) return false;
  if (choice.acceptDefault) return true;
  if (choice.edited) return choice.value.trim() !== "" && (p.dimension === "count" || choice.unit !== "");
  if (p.status === "ok" || p.status === "template_default") return true;
  if (p.status === "needs_confirmation") return choice.confirmed && choice.value.trim() !== "" && (p.dimension === "count" || choice.unit !== "");
  return false;
}

function effective(p: ExtractedParam, choice: Choice): { value: string; unit: string | null } | null {
  if (choice.acceptDefault && p.suggested_default) return { value: p.suggested_default.value ?? "", unit: p.suggested_default.unit ?? null };
  if (!isResolved(p, choice)) return null;
  return { value: choice.value, unit: p.dimension === "count" ? null : choice.unit || null };
}

export function AiEstimate() {
  const router = useRouter();
  const params = useSearchParams();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState(params.get("project") ?? "");
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [units, setUnits] = useState<Unit[]>([]);
  const [text, setText] = useState("");
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [choices, setChoices] = useState<Choices>({});
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [estimates, setEstimates] = useState<Estimate[]>([]);
  const [target, setTarget] = useState<string>("new");
  const [title, setTitle] = useState("Estimate from description");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRaw<Project[]>("/projects?page_size=100")
      .then(({ data }) => {
        setProjects(data);
        setProjectId((current) => current || data[0]?.id || "");
      })
      .catch(() => setProjects([]));
    api<SystemInfo>("/system/info").then(setInfo).catch(() => undefined);
    api<Unit[]>("/units").then(setUnits).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!projectId) return;
    api<Estimate[]>(`/projects/${projectId}/estimates`)
      .then(setEstimates)
      .catch(() => setEstimates([]));
  }, [projectId]);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await post<Extraction>("/ai/extractions", { project_id: projectId, text });
      setExtraction(result);
      setChoices(initialChoices(result));
      setIncluded(Object.fromEntries([...result.components.map((c) => [c.key, true]), ...result.custom_items.map((c) => [c.key, true])]));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not read the description.");
    } finally {
      setBusy(false);
    }
  }

  const unresolved = useMemo(() => {
    if (!extraction) return [];
    return extraction.components
      .filter((c) => included[c.key])
      .flatMap((c) => c.parameters.filter((p) => !isResolved(p, choices[c.key]?.[p.name])).map((p) => `${c.component_name}: ${p.label}`));
  }, [extraction, choices, included]);

  async function confirm() {
    if (!extraction) return;
    setBusy(true);
    setError(null);
    const components = extraction.components.map((c) => ({
      key: c.key,
      include: Boolean(included[c.key]),
      parameters: Object.fromEntries(
        c.parameters.flatMap((p): [string, ParamPayload][] => {
          const choice = choices[c.key]?.[p.name];
          if (!choice) return [];
          if (choice.acceptDefault) return [[p.name, { accept_default: true }]];
          // Only values the user typed or explicitly confirmed are sent; everything else is
          // taken from the extraction on the server, keeping its provenance.
          if (choice.edited || (p.status === "needs_confirmation" && choice.confirmed)) {
            return [[p.name, { value: choice.value, unit: p.dimension === "count" ? null : choice.unit || null }]];
          }
          return [];
        }),
      ),
    }));
    try {
      const result = await post<ConfirmResult>(`/ai/extractions/${extraction.id}/confirm`, {
        estimate_id: target === "new" ? null : target,
        new_estimate_title: target === "new" ? title : null,
        components,
        custom_items: extraction.custom_items.map((c) => ({ key: c.key, include: Boolean(included[c.key]) })),
      });
      router.push(`/projects/${result.project_id}/estimates/${result.estimate_id}?tab=boq`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the BOQ.");
      setBusy(false);
    }
  }

  if (projects === null) return <p className="text-muted">Loading…</p>;
  if (!projects.length) {
    return (
      <div className="max-w-2xl space-y-4">
        <h1 className="text-xl font-semibold">AI Estimate</h1>
        <p className="text-muted">Create a project first; the estimate is added to it.</p>
        <ButtonLink href="/projects/new">New project</ButtonLink>
      </div>
    );
  }

  return (
    <div className="max-w-5xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">AI Estimate</h1>
        {info ? (
          <Badge tone={info.ai_provider === "anthropic" ? "accent" : "neutral"}>
            {info.ai_provider === "anthropic" ? "AI (Claude)" : "Rules-based parser — no AI key configured"}
          </Badge>
        ) : null}
      </div>

      {!extraction ? (
        <Card>
          <form onSubmit={generate} className="space-y-4">
            <Field label="Project">
              <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="max-w-md">
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Describe your proposed work" hint="English, Telugu or Hindi. Include lengths, widths and thicknesses with units.">
              <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} maxLength={4000} placeholder="e.g. Construction of 500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB." />
            </Field>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="text-muted">Examples:</span>
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" onClick={() => setText(ex)} className="rounded border border-line px-2 py-1 text-left hover:bg-panel">
                  {ex.length > 48 ? `${ex.slice(0, 48)}…` : ex}
                </button>
              ))}
            </div>
            {error ? <Alert>{error}</Alert> : null}
            <Button type="submit" disabled={busy || !text.trim() || !projectId}>
              {busy ? "Reading your description…" : "Read description"}
            </Button>
            <p className="text-xs text-muted">
              Nothing is calculated or saved yet. You review every value first; quantities are calculated by the engine only after you confirm.
              No rates are suggested.
            </p>
          </form>
        </Card>
      ) : (
        <Review
          extraction={extraction}
          units={units}
          choices={choices}
          setChoice={(key, name, patch) =>
            setChoices((all) => ({ ...all, [key]: { ...all[key], [name]: { ...all[key]![name]!, ...patch } } }))
          }
          included={included}
          setIncluded={(key, value) => setIncluded((all) => ({ ...all, [key]: value }))}
        />
      )}

      {extraction ? (
        <Card title="Add to">
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex items-center gap-2">
              <input type="radio" name="target" checked={target === "new"} onChange={() => setTarget("new")} /> New estimate
            </label>
            {target === "new" ? <Input aria-label="New estimate title" value={title} onChange={(e) => setTitle(e.target.value)} className="max-w-xs" /> : null}
            {estimates.length ? (
              <label className="flex items-center gap-2">
                <input type="radio" name="target" checked={target !== "new"} onChange={() => setTarget(estimates[0]!.id)} /> Existing estimate
              </label>
            ) : null}
            {target !== "new" ? (
              <Select aria-label="Existing estimate" value={target} onChange={(e) => setTarget(e.target.value)} className="w-auto">
                {estimates.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.estimate_number} — {e.title} (V{e.draft_version_no} draft)
                  </option>
                ))}
              </Select>
            ) : null}
          </div>
          {unresolved.length ? (
            <p className="mt-3 text-xs text-warn">Still needed: {unresolved.join("; ")}.</p>
          ) : null}
          {error ? (
            <div className="mt-3">
              <Alert>{error}</Alert>
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={confirm} disabled={busy || unresolved.length > 0}>
              {busy ? "Creating…" : "Create BOQ"}
            </Button>
            <Button variant="secondary" onClick={() => setExtraction(null)} disabled={busy}>
              Edit description
            </Button>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function Review({
  extraction,
  units,
  choices,
  setChoice,
  included,
  setIncluded,
}: {
  extraction: Extraction;
  units: Unit[];
  choices: Choices;
  setChoice: (key: string, name: string, patch: Partial<Choice>) => void;
  included: Record<string, boolean>;
  setIncluded: (key: string, value: boolean) => void;
}) {
  const source = extraction.provider === "rules" ? "Parsed from your text" : "AI-extracted";
  return (
    <div className="space-y-4">
      <Card>
        <p className="text-muted">“{extraction.input_text}”</p>
        <p className="mt-2 text-xs text-muted">
          {extraction.provider_label}
          {extraction.served_from_cache ? " · same description as before, reused (not counted)" : ""} · Detected:{" "}
          {extraction.project_type ?? "not sure"} · {extraction.components.length} item(s) with formulas
          {extraction.custom_items.length ? `, ${extraction.custom_items.length} without quantity` : ""}
        </p>
        <p className="mt-2 text-xs text-muted">{extraction.disclaimer}</p>
      </Card>

      {extraction.missing_information.length ? (
        <Alert tone="warn">
          <strong>Additional information required</strong>
          <ul className="mt-1 list-disc pl-5">
            {extraction.missing_information.map((m, i) => (
              <li key={i}>
                {m.component_name}: {m.question}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {extraction.components.map((c) => (
        <ComponentCard
          key={c.key}
          component={c}
          units={units}
          choices={choices[c.key] ?? {}}
          setChoice={(name, patch) => setChoice(c.key, name, patch)}
          include={Boolean(included[c.key])}
          setInclude={(v) => setIncluded(c.key, v)}
          sourceLabel={source}
        />
      ))}

      {extraction.custom_items.length ? (
        <Card title="Items without a quantity">
          <p className="mb-2 text-xs text-muted">These are added to the BOQ as items; enter their quantities or measurement lines there.</p>
          {extraction.custom_items.map((c) => (
            <label key={c.key} className="flex items-center gap-2 py-1">
              <input type="checkbox" checked={Boolean(included[c.key])} onChange={(e) => setIncluded(c.key, e.target.checked)} />
              {c.description}
              {c.source_text ? <span className="text-xs text-muted">(“{c.source_text}”)</span> : null}
            </label>
          ))}
        </Card>
      ) : null}

      {extraction.assumptions.length || extraction.warnings.length ? (
        <Card title="Assumptions and notes">
          <ul className="list-disc pl-5 text-muted">
            {[...extraction.assumptions, ...extraction.warnings].map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </Card>
      ) : null}
      {!extraction.components.length && !extraction.custom_items.length ? (
        <Alert tone="info">
          Nothing to add yet. <Link href="/boq" className="underline">Add items on the BOQ page</Link> or edit the description.
        </Alert>
      ) : null}
    </div>
  );
}

function ComponentCard({
  component,
  units,
  choices,
  setChoice,
  include,
  setInclude,
  sourceLabel,
}: {
  component: ExtractedComponent;
  units: Unit[];
  choices: Record<string, Choice>;
  setChoice: (name: string, patch: Partial<Choice>) => void;
  include: boolean;
  setInclude: (v: boolean) => void;
  sourceLabel: string;
}) {
  const [preview, setPreview] = useState<{ key: string; text: string } | null>(null);
  const inputs = component.parameters.map((p) => [p.name, choices[p.name] ? effective(p, choices[p.name]!) : null] as const);
  const complete = inputs.every(([, v]) => v !== null);
  const previewKey = JSON.stringify(inputs);

  useEffect(() => {
    if (!complete || !include) return;
    const timer = setTimeout(() => {
      post<{ display: string; substituted: string }>("/calculate", {
        template_id: component.template_id,
        parameters: Object.fromEntries(inputs.map(([name, v]) => [name, v])),
      })
        .then((r) => setPreview({ key: previewKey, text: `${r.substituted} = ${r.display}` }))
        .catch((e: unknown) => setPreview({ key: previewKey, text: e instanceof ApiError ? e.message : "Cannot calculate yet." }));
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey, include, complete]);

  return (
    <Card
      title={
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={include} onChange={(e) => setInclude(e.target.checked)} aria-label={`Include ${component.component_name}`} />
          {component.component_name}
          <span className="text-xs font-normal text-muted">
            {component.template_name} · result in {component.output_unit_display}
          </span>
        </label>
      }
    >
      <div className={include ? "" : "opacity-50"}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead className="text-xs text-muted uppercase">
              <tr>
                <th className="py-1.5 pr-2">Input</th>
                <th className="w-32 py-1.5 pr-2">Value</th>
                <th className="w-28 py-1.5 pr-2">Unit</th>
                <th className="py-1.5">Source</th>
              </tr>
            </thead>
            <tbody>
              {component.parameters.map((p) => {
                const choice = choices[p.name];
                if (!choice) return null;
                const unitChoices = units.filter((u) => u.dimension === p.dimension);
                return (
                  <tr key={p.name} className="border-t border-line align-top">
                    <td className="py-2 pr-2">
                      {p.label} <span className="font-mono text-xs text-muted">{p.name}</span>
                    </td>
                    <td className="py-2 pr-2">
                      <Input
                        aria-label={`${component.component_name} ${p.label}`}
                        inputMode="decimal"
                        value={choice.acceptDefault ? p.suggested_default?.value ?? "" : choice.value}
                        disabled={!include || choice.acceptDefault}
                        aria-invalid={include && !isResolved(p, choice)}
                        onChange={(e) => setChoice(p.name, { value: e.target.value, edited: true })}
                        className="num py-1 text-right"
                      />
                    </td>
                    <td className="py-2 pr-2">
                      {p.dimension === "count" ? (
                        <span className="text-muted">Nos</span>
                      ) : (
                        <Select
                          aria-label={`${component.component_name} ${p.label} unit`}
                          value={choice.acceptDefault ? p.suggested_default?.unit ?? "" : choice.unit}
                          disabled={!include || choice.acceptDefault}
                          onChange={(e) => setChoice(p.name, { unit: e.target.value, edited: true })}
                          className="py-1"
                        >
                          <option value="">—</option>
                          {unitChoices.map((u) => (
                            <option key={u.code} value={u.code}>
                              {u.display_name}
                            </option>
                          ))}
                        </Select>
                      )}
                    </td>
                    <td className="py-2 text-xs">
                      <SourceCell param={p} choice={choice} sourceLabel={sourceLabel} onChange={(patch) => setChoice(p.name, patch)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="num mt-3 rounded bg-panel px-3 py-2 font-mono text-[13px]">
          {complete && preview?.key === previewKey ? `Preview (calculated by the engine): ${preview.text}` : "Preview appears when every value is filled in."}
        </p>
      </div>
    </Card>
  );
}

function SourceCell({
  param,
  choice,
  sourceLabel,
  onChange,
}: {
  param: ExtractedParam;
  choice: Choice;
  sourceLabel: string;
  onChange: (patch: Partial<Choice>) => void;
}) {
  if (choice.edited) return <Badge>Entered by you</Badge>;
  if (param.status === "ok") {
    return (
      <span>
        <Badge tone="accent">{sourceLabel}</Badge> <span className="text-muted">“{param.source_text}”</span>
      </span>
    );
  }
  if (param.status === "template_default") return <span className="text-muted">{param.note}</span>;
  if (param.status === "needs_confirmation") {
    return (
      <div className="space-y-1">
        <Badge tone="warn">Needs confirmation</Badge> <span className="text-warn">{param.note}</span>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={choice.confirmed} onChange={(e) => onChange({ confirmed: e.target.checked })} /> I confirm this value
        </label>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <span className="font-medium text-bad">Missing.</span> <span className="text-muted">{param.question}</span>
      {param.suggested_default ? (
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={choice.acceptDefault} onChange={(e) => onChange({ acceptDefault: e.target.checked })} className="mt-0.5" />
          <span>
            Use suggested {param.suggested_default.value} {param.suggested_default.unit} — I accept.{" "}
            <span className="text-muted">{param.suggested_default.reason}</span>
          </span>
        </label>
      ) : null}
    </div>
  );
}
