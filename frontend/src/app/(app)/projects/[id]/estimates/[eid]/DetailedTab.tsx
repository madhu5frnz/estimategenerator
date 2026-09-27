"use client";

import { useState } from "react";

import { EditableCell } from "@/components/EditableCell";
import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Field, Input, Select } from "@/components/ui";
import { ApiError, del, patch, post, type Item, type Line, type Parameter, type Template, type Unit, type Version } from "@/lib/api";

import { LENGTH_UNITS, type WorkspaceProps } from "./context";

const LETTERS = "abcdefghijklmnopqrstuvwxyz";
const DIMENSIONS_FOR: Record<string, number> = { volume: 3, area: 2, length: 1, count: 0 };

export function DetailedTab(props: WorkspaceProps) {
  const { version } = props;
  const items = version.sections.flatMap((s) => s.items.map((i) => ({ section: s.title, item: i })));
  const [calculation, setCalculation] = useState<{ item: Item; line: Line } | null>(null);
  const [formulaFor, setFormulaFor] = useState<{ item: Item; line?: Line } | null>(null);

  if (!items.length) {
    return <p className="rounded border border-dashed border-line p-6 text-center text-muted">Add items on the BOQ tab first.</p>;
  }

  return (
    <div className="space-y-5">
      <p className="text-xs text-muted">
        Each line is calculated by the server. Blank dimensions are not used: an item in Cum needs L, B and D/H; Sq.m needs two
        dimensions; Rmt one; Nos only No. Deduction lines subtract.
      </p>
      {items.map(({ section, item }) => (
        <ItemLines
          key={item.id}
          item={item}
          section={section}
          {...props}
          onView={(line) => setCalculation({ item, line })}
          onFormula={(line) => setFormulaFor({ item, line })}
        />
      ))}
      {calculation ? <CalculationDialog {...calculation} onClose={() => setCalculation(null)} /> : null}
      {formulaFor ? (
        <FormulaDialog
          {...formulaFor}
          templates={props.templates}
          units={props.units}
          parameters={version.parameters}
          onClose={() => setFormulaFor(null)}
          onSave={async (body) => {
            await props.mutate(() =>
              formulaFor.line
                ? patch<Version>(`/measurements/${formulaFor.line.id}`, body)
                : post<Version>(`/boq-items/${formulaFor.item.id}/measurements`, body),
            );
            setFormulaFor(null);
          }}
        />
      ) : null}
    </div>
  );
}

function ItemLines({
  item,
  section,
  mutate,
  units,
  editable,
  onView,
  onFormula,
}: WorkspaceProps & { item: Item; section: string; onView: (line: Line) => void; onFormula: (line?: Line) => void }) {
  const unit = units.find((u) => u.code === item.unit);
  const needed = unit ? DIMENSIONS_FOR[unit.dimension] : undefined;
  const lengthUnits = units.filter((u) => LENGTH_UNITS.includes(u.code));
  const save = (line: Line, field: string) => (value: string) =>
    mutate(() => patch<Version>(`/measurements/${line.id}`, { [field]: value.trim() === "" ? null : value }));

  return (
    <section aria-label={`Item ${item.sl_no}`} className="rounded border border-line">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line bg-panel px-3 py-2">
        <div>
          <span className="mr-2 font-semibold">{item.item_no_display}</span>
          <span>{item.description}</span>
          <span className="ml-2 text-xs text-muted">{section}</span>
        </div>
        <div className="num text-right">
          <span className="text-xs text-muted">Quantity </span>
          <span className="font-semibold">
            {item.quantity ?? "—"} {item.unit_display ?? ""}
          </span>
          {item.quantity_source === "manual" && item.quantity ? <Badge>entered directly</Badge> : null}
        </div>
      </header>
      {!item.unit ? (
        <p className="p-3 text-xs text-muted">Set the item’s unit on the BOQ tab to add measurement lines.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left">
            <thead className="text-xs text-muted uppercase">
              <tr>
                <th className="w-10 px-2 py-1.5">Sl</th>
                <th className="px-2 py-1.5">Description</th>
                <th className="w-20 px-2 py-1.5 text-right">No</th>
                <th className="w-24 px-2 py-1.5 text-right">L</th>
                <th className="w-24 px-2 py-1.5 text-right">B</th>
                <th className="w-24 px-2 py-1.5 text-right">D/H</th>
                <th className="w-20 px-2 py-1.5">In</th>
                <th className="w-28 px-2 py-1.5 text-right">Quantity</th>
                <th className="w-44 px-2 py-1.5" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {item.lines.map((line, index) => (
                <tr key={line.id} className={`border-t border-line align-top ${line.is_deduction ? "bg-amber-50/50" : ""}`}>
                  <td className="px-2 py-1.5 text-muted">{LETTERS[index] ?? index + 1}</td>
                  <td>
                    <EditableCell label="Line description" value={line.description} editable={editable} onSave={save(line, "description")} />
                  </td>
                  {line.mode === "dimensions" ? (
                    <>
                      {(["nos", "length", "breadth", "depth_height"] as const).map((f) => (
                        <td key={f}>
                          <EditableCell
                            label={{ nos: "No", length: "L", breadth: "B", depth_height: "D/H" }[f]}
                            value={line[f]}
                            numeric
                            editable={editable}
                            onSave={save(line, f)}
                          />
                        </td>
                      ))}
                      <td className="px-1 py-1">
                        {editable && needed ? (
                          <Select
                            aria-label="Dimension unit"
                            value={line.dimension_unit ?? "m"}
                            onChange={(e) => void save(line, "dimension_unit")(e.target.value).catch(() => undefined)}
                            className="w-20 px-1 py-1"
                          >
                            {lengthUnits.map((u) => (
                              <option key={u.code} value={u.code}>
                                {u.display_name}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <div className="px-2 py-1.5 text-muted">{needed ? line.dimension_unit : ""}</div>
                        )}
                      </td>
                    </>
                  ) : (
                    <td colSpan={5} className="px-2 py-1.5 font-mono text-xs text-muted">
                      {line.calculation?.substituted}
                    </td>
                  )}
                  <td className={`num px-2 py-1.5 text-right ${line.is_deduction ? "text-warn" : ""}`}>
                    {line.is_deduction ? `(−) ${line.quantity}` : line.quantity}
                  </td>
                  <td className="px-2 py-1 text-right text-xs whitespace-nowrap">
                    <button className="text-accent hover:underline" onClick={() => onView(line)}>
                      View calculation
                    </button>
                    {editable ? (
                      <>
                        {line.mode === "formula" ? (
                          <button className="ml-2 text-accent hover:underline" onClick={() => onFormula(line)}>
                            Edit
                          </button>
                        ) : null}
                        <button
                          className="ml-2 text-muted hover:underline"
                          onClick={() => void mutate(() => patch<Version>(`/measurements/${line.id}`, { is_deduction: !line.is_deduction })).catch(() => undefined)}
                          title="Toggle deduction"
                        >
                          {line.is_deduction ? "Add" : "Deduct"}
                        </button>
                        <button
                          className="ml-2 text-bad hover:underline"
                          onClick={() => void mutate(() => del<Version>(`/measurements/${line.id}`)).catch(() => undefined)}
                          aria-label="Delete line"
                        >
                          ✕
                        </button>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
              {!item.lines.length ? (
                <tr className="border-t border-line">
                  <td colSpan={9} className="px-2 py-2 text-xs text-muted">
                    No measurement lines. {item.quantity_source === "manual" && item.quantity ? "The BOQ quantity was entered directly." : ""}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          {editable ? (
            <div className="border-t border-line px-2 py-2">
              <AddLineRow item={item} needed={needed} lengthUnits={lengthUnits} mutate={mutate} onFormula={() => onFormula()} />
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function AddLineRow({
  item,
  needed,
  lengthUnits,
  mutate,
  onFormula,
}: {
  item: Item;
  needed: number | undefined;
  lengthUnits: Unit[];
  mutate: WorkspaceProps["mutate"];
  onFormula: () => void;
}) {
  const empty = { description: "", nos: "1", length: "", breadth: "", depth_height: "", dimension_unit: "m" };
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  const dims = (["length", "breadth", "depth_height"] as const).slice(0, needed ?? 0);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {needed === undefined ? (
        <span className="text-xs text-muted">This unit is measured with a formula line.</span>
      ) : (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await mutate(() =>
                post<Version>(`/boq-items/${item.id}/measurements`, {
                  description: form.description || null,
                  nos: form.nos || "1",
                  length: dims.includes("length") ? form.length || null : null,
                  breadth: dims.includes("breadth") ? form.breadth || null : null,
                  depth_height: dims.includes("depth_height") ? form.depth_height || null : null,
                  dimension_unit: form.dimension_unit,
                }),
              );
              setForm(empty);
            } catch {
              // shown by the workspace
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input aria-label="New line description" placeholder="Add line, e.g. Ch 0–500" value={form.description} onChange={set("description")} className="w-56 py-1" />
          <Input aria-label="New line No" placeholder="No" inputMode="decimal" value={form.nos} onChange={set("nos")} className="num w-16 py-1 text-right" />
          {dims.map((d) => (
            <Input
              key={d}
              aria-label={`New line ${{ length: "L", breadth: "B", depth_height: "D/H" }[d]}`}
              placeholder={{ length: "L", breadth: "B", depth_height: "D/H" }[d]}
              inputMode="decimal"
              value={form[d]}
              onChange={set(d)}
              className="num w-24 py-1 text-right"
            />
          ))}
          {dims.length ? (
            <Select aria-label="New line unit" value={form.dimension_unit} onChange={set("dimension_unit")} className="w-20 px-1 py-1">
              {lengthUnits.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.display_name}
                </option>
              ))}
            </Select>
          ) : null}
          <Button type="submit" variant="secondary" className="py-1" disabled={busy}>
            Add line
          </Button>
        </form>
      )}
      <Button type="button" variant="ghost" className="py-1 text-accent" onClick={onFormula}>
        + Formula line
      </Button>
    </div>
  );
}

function CalculationDialog({ item, line, onClose }: { item: Item; line: Line; onClose: () => void }) {
  const calc = line.calculation;
  return (
    <Modal title={`Calculation — ${item.item_no_display} (${line.description})`} onClose={onClose}>
      {calc ? (
        <div className="space-y-3">
          <ol className="num space-y-1 rounded bg-panel p-3 font-mono text-[13px]">
            {calc.steps.map((s, i) => (
              <li key={i} className={s.kind === "result" ? "font-semibold" : ""}>
                {s.text}
              </li>
            ))}
          </ol>
          {Object.entries(calc.inputs).some(([, v]) => (v as { ref?: string }).ref) ? (
            <p className="text-xs text-muted">
              Uses parameters:{" "}
              {Object.entries(calc.inputs)
                .filter(([, v]) => (v as { ref?: string }).ref)
                .map(([k, v]) => `${k} ← ${(v as { ref: string }).ref}`)
                .join(", ")}
            </p>
          ) : null}
          {line.is_deduction ? <p className="text-xs text-warn">This line is a deduction and is subtracted from the item.</p> : null}
          <p className="text-xs text-muted">
            {calc.template_id ? `Template ${calc.template_id} v${calc.template_version} · ` : ""}Engine {calc.engine_version}. Calculation check
            passed (arithmetic and units only, not engineering correctness).
          </p>
        </div>
      ) : (
        <p className="text-muted">No calculation stored for this line.</p>
      )}
    </Modal>
  );
}

type InputState = { source: "value" | "ref"; value: string; unit: string; ref: string };

function FormulaDialog({
  item,
  line,
  templates,
  units,
  parameters,
  onClose,
  onSave,
}: {
  item: Item;
  line?: Line;
  templates: Template[];
  units: Unit[];
  parameters: Parameter[];
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const existing = line?.calculation;
  const [mode, setMode] = useState<"template" | "custom">(existing && !existing.template_id ? "custom" : "template");
  const [templateId, setTemplateId] = useState(existing?.template_id ?? templates[0]?.id ?? "");
  const [expression, setExpression] = useState(existing && !existing.template_id ? existing.expression : "L * B * H");
  const [description, setDescription] = useState(line?.description ?? "");
  const [deduction, setDeduction] = useState(line?.is_deduction ?? false);
  const [inputs, setInputs] = useState<Record<string, InputState>>(() => {
    const out: Record<string, InputState> = {};
    for (const [name, raw] of Object.entries(existing?.inputs ?? {})) {
      const v = raw as { value?: string; unit?: string | null; ref?: string };
      out[name] = { source: v.ref ? "ref" : "value", value: v.value ?? "", unit: v.unit ?? "", ref: v.ref ?? "" };
    }
    return out;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const template = templates.find((t) => t.id === templateId);
  const customNames = Array.from(new Set(expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [])).filter(
    (n) => !["pi", "min", "max", "round", "sqrt", "abs", "ceil", "floor"].includes(n),
  );
  const fields =
    mode === "template"
      ? (template?.parameters ?? []).map((p) => ({ name: p.name, label: p.label, dimension: p.dimension, required: p.required, fallback: p.canonical_unit ?? "" }))
      : customNames.map((n) => ({ name: n, label: n, dimension: "", required: true, fallback: "m" }));

  const get = (name: string, fallbackUnit: string): InputState => inputs[name] ?? { source: "value", value: "", unit: fallbackUnit, ref: "" };
  const update = (name: string, fallbackUnit: string, patchState: Partial<InputState>) =>
    setInputs((all) => ({ ...all, [name]: { ...get(name, fallbackUnit), ...patchState } }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {
      mode: "formula",
      description: description || null,
      is_deduction: deduction,
      template_id: mode === "template" ? templateId : null,
      expression: mode === "custom" ? expression : null,
      inputs: Object.fromEntries(
        fields
          .map((f) => [f.name, get(f.name, f.fallback)] as const)
          .filter(([, s]) => s.source === "ref" ? s.ref : s.value.trim() !== "")
          .map(([name, s]) => [name, s.source === "ref" ? { ref: s.ref } : { value: s.value, unit: s.unit || null }]),
      ),
    };
    setBusy(true);
    setError(null);
    try {
      await onSave(body);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The line could not be saved.");
      setBusy(false);
    }
  }

  return (
    <Modal title={`${line ? "Edit" : "Add"} formula line — ${item.item_no_display}`} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}
        <div className="flex gap-2">
          {(["template", "custom"] as const).map((m) => (
            <Button key={m} type="button" variant={mode === m ? "primary" : "secondary"} onClick={() => setMode(m)} className="py-1">
              {m === "template" ? "Standard formula" : "Custom formula"}
            </Button>
          ))}
        </div>
        {mode === "template" ? (
          <Field label="Formula">
            <Select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} — {t.expression_display} ({t.output_unit_display})
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field label="Formula" hint="Use + − × / ^ ( ), pi, min, max, round, sqrt. The result is in the item’s unit.">
            <Input value={expression} onChange={(e) => setExpression(e.target.value)} className="font-mono" />
          </Field>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Line description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Carriageway" />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2">
            <input type="checkbox" checked={deduction} onChange={(e) => setDeduction(e.target.checked)} /> Deduction (subtract)
          </label>
        </div>

        <table className="w-full text-left">
          <thead className="text-xs text-muted uppercase">
            <tr>
              <th className="py-1">Input</th>
              <th className="py-1">From</th>
              <th className="py-1">Value</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => {
              const state = get(f.name, f.fallback);
              const unitChoices = f.dimension === "count" ? [] : units.filter((u) => (f.dimension ? u.dimension === f.dimension : !["lump_sum", "other"].includes(u.dimension)));
              return (
                <tr key={f.name} className="border-t border-line">
                  <td className="py-2 pr-2">
                    {f.label} <span className="font-mono text-xs text-muted">{f.name}</span>
                    {!f.required ? <span className="block text-xs text-muted">optional</span> : null}
                  </td>
                  <td className="py-2 pr-2">
                    <Select aria-label={`${f.name} source`} value={state.source} onChange={(e) => update(f.name, f.fallback, { source: e.target.value as "value" | "ref" })} className="w-auto py-1">
                      <option value="value">Value</option>
                      <option value="ref" disabled={!parameters.length}>
                        Parameter
                      </option>
                    </Select>
                  </td>
                  <td className="py-2">
                    {state.source === "ref" ? (
                      <Select aria-label={`${f.name} parameter`} value={state.ref} onChange={(e) => update(f.name, f.fallback, { ref: e.target.value })} className="py-1">
                        <option value="">Choose…</option>
                        {parameters.map((p) => (
                          <option key={p.id} value={p.name}>
                            {p.label} ({p.value ?? "no value"} {p.unit_display ?? ""})
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <div className="flex gap-2">
                        <Input aria-label={`${f.name} value`} inputMode="decimal" value={state.value} onChange={(e) => update(f.name, f.fallback, { value: e.target.value })} className="num w-32 py-1 text-right" />
                        {unitChoices.length ? (
                          <Select aria-label={`${f.name} unit`} value={state.unit} onChange={(e) => update(f.name, f.fallback, { unit: e.target.value })} className="w-auto py-1">
                            {!f.dimension ? <option value="">(plain number)</option> : null}
                            {unitChoices.map((u) => (
                              <option key={u.code} value={u.code}>
                                {u.display_name}
                              </option>
                            ))}
                          </Select>
                        ) : null}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {line ? "Save line" : "Add line"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
