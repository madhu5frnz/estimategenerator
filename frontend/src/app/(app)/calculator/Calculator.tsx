"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type Calculation, type ParamValue, type Template, type Unit } from "@/lib/api";

type Mode = "template" | "custom";
type LoadState = { templates: Template[]; units: Unit[] } | { error: string } | null;

const LENGTH_FIRST = ["m", "mm", "cm", "km", "ft"];

function unitsFor(units: Unit[], dimension: string): Unit[] {
  const list = units.filter((u) => u.dimension === dimension);
  return dimension === "length"
    ? [...list].sort((a, b) => LENGTH_FIRST.indexOf(a.code) - LENGTH_FIRST.indexOf(b.code))
    : list;
}

const formulaUnits = (units: Unit[]) =>
  units.filter((u) => !["lump_sum", "other"].includes(u.dimension));

export function Calculator() {
  const [loaded, setLoaded] = useState<LoadState>(null);
  const [mode, setMode] = useState<Mode>("template");
  const [templateId, setTemplateId] = useState("road_layer");
  const [expression, setExpression] = useState("L * B * H");
  const [outputUnit, setOutputUnit] = useState("cum");
  const [customNames, setCustomNames] = useState<string[]>(["B", "H", "L"]);
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  const [result, setResult] = useState<Calculation | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([api<Template[]>("/calculation-templates"), api<Unit[]>("/units")])
      .then(([templates, units]) => setLoaded({ templates, units }))
      .catch((e: unknown) =>
        setLoaded({ error: e instanceof ApiError ? e.message : "Could not load templates." }),
      );
  }, []);

  const templates = loaded && "templates" in loaded ? loaded.templates : [];
  const units = loaded && "units" in loaded ? loaded.units : [];
  const template = templates.find((t) => t.id === templateId);

  const reset = () => {
    setParams({});
    setResult(null);
    setError(null);
  };

  const setParam = (name: string, patch: Partial<ParamValue>) =>
    setParams((prev) => ({
      ...prev,
      [name]: { value: prev[name]?.value ?? "", unit: prev[name]?.unit ?? null, ...patch },
    }));

  async function readFormula() {
    setError(null);
    try {
      const parsed = await api<{ expression_display: string; parameters: string[] }>(
        "/calculate/validate-expression",
        { method: "POST", body: JSON.stringify({ expression }) },
      );
      setCustomNames(parsed.parameters);
    } catch (e) {
      if (e instanceof ApiError) setError(e);
    }
  }

  async function calculate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const names =
      mode === "template" ? (template?.parameters.map((p) => p.name) ?? []) : customNames;
    const parameters: Record<string, ParamValue> = {};
    for (const name of names) {
      const p = params[name];
      const fallbackUnit =
        mode === "template"
          ? (template?.parameters.find((tp) => tp.name === name)?.canonical_unit ?? null)
          : null;
      parameters[name] = { value: p?.value ?? "", unit: p?.unit ?? fallbackUnit };
    }
    const body =
      mode === "template"
        ? { template_id: templateId, parameters }
        : { expression, output_unit: outputUnit, parameters };
    try {
      setResult(await api<Calculation>("/calculate", { method: "POST", body: JSON.stringify(body) }));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e : new ApiError("UNKNOWN", "Calculation failed."));
    } finally {
      setBusy(false);
    }
  }

  if (loaded === null) return <p className="text-muted">Loading…</p>;
  if ("error" in loaded) return <p className="text-bad">{loaded.error}</p>;

  const missing = new Set(
    error?.errorCode === "MISSING_PARAMETER" ? ((error.details.parameters as string[]) ?? []) : [],
  );

  return (
    <div className="max-w-4xl">
      <h1 className="text-xl font-semibold">Quantity Calculator</h1>
      <p className="mt-1 text-muted">
        Quantities are calculated by the server&apos;s calculation engine. Every step is shown.
      </p>

      <div role="tablist" className="mt-5 inline-flex rounded border border-line p-0.5">
        {(["template", "custom"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            onClick={() => {
              setMode(m);
              reset();
            }}
            className={`rounded px-3 py-1.5 ${mode === m ? "bg-accent text-white" : "text-ink hover:bg-panel"}`}
          >
            {m === "template" ? "Standard formula" : "Custom formula"}
          </button>
        ))}
      </div>

      <form onSubmit={calculate} className="mt-5 space-y-4">
        {mode === "template" ? (
          <label className="block">
            <span className="mb-1 block font-medium">Formula</span>
            <select
              value={templateId}
              onChange={(e) => {
                setTemplateId(e.target.value);
                reset();
              }}
              className="w-full max-w-md rounded border border-line bg-white px-3 py-2"
            >
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} — {t.expression_display}
                </option>
              ))}
            </select>
            {template?.description ? (
              <span className="mt-1 block text-xs text-muted">{template.description}</span>
            ) : null}
          </label>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <label className="block grow">
              <span className="mb-1 block font-medium">Formula</span>
              <input
                value={expression}
                onChange={(e) => setExpression(e.target.value)}
                onBlur={readFormula}
                className="w-full rounded border border-line px-3 py-2 font-mono"
                placeholder="e.g. (L * H - openings) * T"
              />
            </label>
            <label className="block">
              <span className="mb-1 block font-medium">Result unit</span>
              <select
                value={outputUnit}
                onChange={(e) => setOutputUnit(e.target.value)}
                className="rounded border border-line bg-white px-3 py-2"
              >
                {formulaUnits(units).map((u) => (
                  <option key={u.code} value={u.code}>
                    {u.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={readFormula} className="rounded border border-line px-3 py-2 hover:bg-panel">
              Read formula
            </button>
          </div>
        )}

        <table className="w-full max-w-2xl border-collapse">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted uppercase">
              <th className="py-2 pr-3">Parameter</th>
              <th className="py-2 pr-3">Value</th>
              <th className="py-2">Unit</th>
            </tr>
          </thead>
          <tbody>
            {(mode === "template"
              ? (template?.parameters ?? [])
              : customNames.map((n) => ({
                  name: n,
                  label: n,
                  dimension: "",
                  required: true,
                  default: null,
                  canonical_unit: null,
                }))
            ).map((p) => {
              const choices =
                mode === "template"
                  ? p.dimension === "count"
                    ? []
                    : unitsFor(units, p.dimension)
                  : formulaUnits(units);
              const current = params[p.name];
              return (
                <tr key={p.name} className="border-b border-line">
                  <td className="py-2 pr-3">
                    <span className="font-medium">{p.label}</span>
                    {p.label !== p.name ? (
                      <span className="ml-2 font-mono text-xs text-muted">{p.name}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">
                    <input
                      inputMode="decimal"
                      aria-label={p.label}
                      aria-invalid={missing.has(p.name)}
                      value={current?.value ?? ""}
                      onChange={(e) => setParam(p.name, { value: e.target.value })}
                      placeholder={p.default !== null ? `default ${p.default}` : "required"}
                      className={`num w-36 rounded border px-2 py-1.5 ${missing.has(p.name) ? "border-bad" : "border-line"}`}
                    />
                  </td>
                  <td className="py-2">
                    {choices.length ? (
                      <select
                        aria-label={`${p.label} unit`}
                        value={current?.unit ?? p.canonical_unit ?? ""}
                        onChange={(e) => setParam(p.name, { unit: e.target.value || null })}
                        className="rounded border border-line bg-white px-2 py-1.5"
                      >
                        {mode === "custom" ? <option value="">(plain number)</option> : null}
                        {choices.map((u) => (
                          <option key={u.code} value={u.code}>
                            {u.display_name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-muted">Nos</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-4 py-2 font-medium text-white disabled:opacity-60"
        >
          {busy ? "Calculating…" : "Calculate"}
        </button>
      </form>

      {error ? (
        <div role="alert" className="mt-5 rounded border border-bad/40 bg-red-50 p-3 text-bad">
          {error.message}
          {error.requestId ? (
            <span className="mt-1 block text-xs opacity-70">Request id: {error.requestId}</span>
          ) : null}
        </div>
      ) : null}

      {result ? (
        <section aria-label="Calculation" className="mt-6 rounded border border-line">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line bg-panel px-4 py-3">
            <span className="num text-2xl font-semibold">{result.display}</span>
            <span className="text-xs text-ok">✓ {result.check}</span>
          </div>
          <ol className="num space-y-1 px-4 py-3 font-mono text-[13px]">
            {result.steps.map((s, i) => (
              <li key={i} className={s.kind === "result" ? "font-semibold" : ""}>
                {s.text}
              </li>
            ))}
          </ol>
          <p className="border-t border-line px-4 py-2 text-xs text-muted">
            {result.template_id ? `Template ${result.template_id} v${result.template_version} · ` : "Custom formula · "}
            Engine {result.engine_version}. The check covers arithmetic and units only, not
            engineering correctness.
          </p>
        </section>
      ) : null}
    </div>
  );
}
