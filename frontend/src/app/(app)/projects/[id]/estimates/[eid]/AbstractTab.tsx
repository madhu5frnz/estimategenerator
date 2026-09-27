"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError, del, patch, post, put, type Abstract, type Charge, type GstConfig, type Version } from "@/lib/api";
import { inr } from "@/lib/format";

import type { WorkspaceProps } from "./context";

const KINDS: [string, string][] = [
  ["contingency", "Contingencies"],
  ["work_charged_establishment", "Work-charged establishment"],
  ["labour_cess", "Labour welfare cess"],
  ["seigniorage", "Seigniorage"],
  ["royalty", "Royalty"],
  ["other", "Other"],
];
const ROUNDING: [string, string][] = [
  ["none", "No rounding"],
  ["nearest_rupee", "Nearest ₹1"],
  ["nearest_10", "Nearest ₹10"],
  ["nearest_100", "Nearest ₹100"],
  ["nearest_1000", "Nearest ₹1,000"],
];

export function AbstractTab({ version, mutate }: WorkspaceProps) {
  const vid = version.version.id;
  const [data, setData] = useState<Abstract | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reload whenever the version changes (item edits change the section totals).
  useEffect(() => {
    let cancelled = false;
    api<Abstract>(`/versions/${vid}/abstract`)
      .then((a) => !cancelled && setData(a))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the abstract."));
    return () => {
      cancelled = true;
    };
  }, [vid, version]);

  /** Every change returns the recalculated abstract; the BOQ header totals follow. */
  async function change(request: () => Promise<Abstract>): Promise<boolean> {
    setError(null);
    try {
      setData(await request());
      await mutate(() => api<Version>(`/versions/${vid}`)).catch(() => undefined);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The change could not be saved.");
      return false;
    }
  }

  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const edit = data.can_edit;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-3">
        {error ? <Alert>{error}</Alert> : null}
        {data.problem ? <Alert tone="warn">{data.problem.message} The totals below leave GST out until it is set.</Alert> : null}
        <div className="overflow-x-auto rounded border border-line">
          <table className="w-full min-w-[620px] text-left">
            <thead className="bg-panel text-xs text-muted uppercase">
              <tr>
                <th className="w-14 px-2 py-2">Sl.No</th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2">Basis</th>
                <th className="w-40 px-2 py-2 text-right">Amount ₹</th>
                {edit ? <th className="w-28 px-2 py-2" aria-label="Actions" /> : null}
              </tr>
            </thead>
            <tbody>
              {data.sections.map((s) => (
                <tr key={s.id} className="border-t border-line">
                  <td className="px-2 py-1.5">{s.sl_no}</td>
                  <td className="px-2 py-1.5">{s.title}</td>
                  <td className="px-2 py-1.5 text-xs text-muted">{s.item_count} item(s)</td>
                  <td className="num px-2 py-1.5 text-right">{inr(s.amount).slice(1)}</td>
                  {edit ? <td /> : null}
                </tr>
              ))}
              <Total label="Works subtotal" value={data.works_subtotal} edit={edit} strong />
              {data.charges.map((c, i) => (
                <ChargeRow
                  key={c.id}
                  charge={c}
                  edit={edit}
                  first={i === 0}
                  last={i === data.charges.length - 1}
                  onChange={(body) => change(() => patch<Abstract>(`/charges/${c.id}`, body))}
                  onDelete={() => change(() => del<Abstract>(`/charges/${c.id}`))}
                  onMove={(delta) => {
                    const ids = data.charges.map((x) => x.id);
                    ids.splice(i, 1);
                    ids.splice(i + delta, 0, c.id);
                    return change(() => post<Abstract>(`/versions/${vid}/charges/reorder`, { ids }));
                  }}
                />
              ))}
              {data.charges.length ? <Total label="Subtotal before GST" value={data.subtotal_before_gst} edit={edit} strong /> : null}
              {data.gst.map((g) => (
                <tr key={g.name} className="border-t border-line">
                  <td />
                  <td className="px-2 py-1.5">
                    {g.name} @ {g.rate_pct} %{g.included ? <span className="text-xs text-muted"> (included in the rates, not added)</span> : null}
                  </td>
                  <td className="px-2 py-1.5 text-xs text-muted">on {inr(g.base_amount)}</td>
                  <td className={`num px-2 py-1.5 text-right ${g.included ? "text-muted" : ""}`}>{inr(g.amount).slice(1)}</td>
                  {edit ? <td /> : null}
                </tr>
              ))}
              {data.rounding_adjustment !== "0.00" ? (
                <>
                  <Total label="Total" value={data.total_before_rounding} edit={edit} />
                  <Total label="Rounding off" value={data.rounding_adjustment} edit={edit} />
                </>
              ) : null}
            </tbody>
            <tfoot className="border-t-2 border-line bg-panel">
              <tr>
                <td />
                <td colSpan={2} className="px-2 py-2 font-semibold">
                  Grand total
                </td>
                <td className="num px-2 py-2 text-right font-semibold">{inr(data.grand_total)}</td>
                {edit ? <td /> : null}
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="text-sm">{data.amount_in_words}</p>
        {data.notes.map((n) => (
          <p key={n} className="text-xs text-muted">
            {n}
          </p>
        ))}
        {edit ? <AddCharge data={data} onAdd={(body) => change(() => post<Abstract>(`/versions/${vid}/charges`, body))} /> : null}
      </div>

      <div className="space-y-4">
        <GstPanel key={JSON.stringify(data.gst_config)} config={data.gst_config} edit={edit} onSave={(body) => change(() => put<Abstract>(`/versions/${vid}/gst`, body))} />
        <Card title="Rounding">
          <Select
            aria-label="Grand total rounding"
            value={data.rounding}
            disabled={!edit}
            onChange={(e) => void change(() => put<Abstract>(`/versions/${vid}/rounding`, { grand_total: e.target.value }))}
          >
            {ROUNDING.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
          <p className="mt-2 text-xs text-muted">Applies to the grand total only; item amounts are always to the paisa.</p>
        </Card>
      </div>
    </div>
  );
}

function Total({ label, value, edit, strong }: { label: string; value: string; edit: boolean; strong?: boolean }) {
  return (
    <tr className={`border-t border-line ${strong ? "bg-panel/60 font-semibold" : ""}`}>
      <td />
      <td colSpan={2} className="px-2 py-1.5">
        {label}
      </td>
      <td className="num px-2 py-1.5 text-right">{inr(value).slice(1)}</td>
      {edit ? <td /> : null}
    </tr>
  );
}

function ChargeRow({
  charge: c,
  edit,
  first,
  last,
  onChange,
  onDelete,
  onMove,
}: {
  charge: Charge;
  edit: boolean;
  first: boolean;
  last: boolean;
  onChange: (body: Record<string, unknown>) => Promise<boolean>;
  onDelete: () => Promise<boolean>;
  onMove: (delta: number) => Promise<boolean>;
}) {
  const btn = "rounded px-1.5 py-1 text-xs text-muted hover:bg-panel hover:text-ink disabled:opacity-30";
  return (
    <tr className={`border-t border-line ${c.enabled ? "" : "text-muted line-through"}`}>
      <td />
      <td className="px-2 py-1.5">
        {c.name}
        {c.percentage !== null ? ` @ ${c.percentage} %` : ""}
      </td>
      <td className="px-2 py-1.5 text-xs text-muted">
        {c.percentage !== null ? `on ${c.base_label} (${inr(c.base_amount)})` : c.base_label}
      </td>
      <td className="num px-2 py-1.5 text-right">{inr(c.amount).slice(1)}</td>
      {edit ? (
        <td className="px-1 py-1">
          <div className="flex items-center justify-end gap-0.5">
            <input
              type="checkbox"
              aria-label={`Include ${c.name}`}
              title="Include in the total"
              checked={c.enabled}
              onChange={(e) => void onChange({ enabled: e.target.checked })}
            />
            <button className={btn} disabled={first} onClick={() => void onMove(-1)} aria-label="Move up">
              ↑
            </button>
            <button className={btn} disabled={last} onClick={() => void onMove(1)} aria-label="Move down">
              ↓
            </button>
            <button
              className={`${btn} hover:text-bad`}
              aria-label={`Delete ${c.name}`}
              onClick={() => window.confirm(`Remove “${c.name}”?`) && void onDelete()}
            >
              ✕
            </button>
          </div>
        </td>
      ) : null}
    </tr>
  );
}

function AddCharge({ data, onAdd }: { data: Abstract; onAdd: (body: Record<string, unknown>) => Promise<boolean> }) {
  const empty = { kind: "contingency", name: "Contingencies", type: "percentage", value: "", base: "works_subtotal" };
  const [form, setForm] = useState(empty);
  const [sections, setSections] = useState<string[]>([]);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  const ready = form.name.trim() && form.value.trim() && (form.base !== "sections" || sections.length > 0);

  return (
    <Card title="Add a charge">
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await onAdd({
            name: form.name,
            kind: form.kind,
            [form.type]: form.value,
            base: form.type === "percentage" ? form.base : "works_subtotal",
            section_keys: form.base === "sections" ? sections : [],
          });
          if (ok) {
            setForm({ ...empty, kind: "other", name: "" });
            setSections([]);
          }
        }}
      >
        <Field label="Type">
          <Select
            value={form.kind}
            onChange={(e) => {
              const label = KINDS.find(([k]) => k === e.target.value)?.[1] ?? "";
              setForm((f) => ({ ...f, kind: e.target.value, name: e.target.value === "other" ? "" : label }));
            }}
          >
            {KINDS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Name shown in the abstract" required>
          <Input value={form.name} onChange={set("name")} maxLength={120} />
        </Field>
        <Field label="Amount">
          <div className="flex gap-2">
            <Select aria-label="Percentage or fixed amount" value={form.type} onChange={set("type")} className="w-32">
              <option value="percentage">%</option>
              <option value="fixed_amount">Fixed ₹</option>
            </Select>
            <Input
              aria-label={form.type === "percentage" ? "Percentage" : "Fixed amount"}
              inputMode="decimal"
              placeholder={form.type === "percentage" ? "e.g. 3" : "e.g. 25000"}
              value={form.value}
              onChange={set("value")}
              className="num text-right"
            />
          </div>
        </Field>
        {form.type === "percentage" ? (
          <Field label="Calculated on">
            <Select value={form.base} onChange={set("base")}>
              <option value="works_subtotal">Works subtotal</option>
              <option value="running_total">Running total (subtotal + charges above)</option>
              <option value="sections">Chosen sections</option>
            </Select>
          </Field>
        ) : null}
        {form.type === "percentage" && form.base === "sections" ? (
          <fieldset className="sm:col-span-2">
            <legend className="mb-1 text-xs text-muted">Sections</legend>
            <div className="flex flex-wrap gap-3">
              {data.sections.map((s) => (
                <label key={s.line_key} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={sections.includes(s.line_key)}
                    onChange={(e) =>
                      setSections((cur) => (e.target.checked ? [...cur, s.line_key] : cur.filter((k) => k !== s.line_key)))
                    }
                  />
                  {s.sl_no}. {s.title}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
        <div className="sm:col-span-2">
          <Button type="submit" variant="secondary" disabled={!ready}>
            Add charge
          </Button>
          <p className="mt-2 text-xs text-muted">Nothing is added automatically. Enter the percentages your department applies.</p>
        </div>
      </form>
    </Card>
  );
}

function GstPanel({ config, edit, onSave }: { config: GstConfig; edit: boolean; onSave: (body: GstConfig) => Promise<boolean> }) {
  const [form, setForm] = useState<GstConfig>(config);
  const dirty = JSON.stringify(form) !== JSON.stringify(config);
  const set = <K extends keyof GstConfig>(key: K, value: GstConfig[K]) => setForm((f) => ({ ...f, [key]: value }));
  return (
    <Card title="GST" actions={config.applicable ? <Badge tone="accent">{config.rate_pct} %</Badge> : <Badge>Off</Badge>}>
      <div className="space-y-3">
        <label className="flex items-center gap-2">
          <input type="checkbox" disabled={!edit} checked={form.applicable} onChange={(e) => set("applicable", e.target.checked)} />
          Add GST to this estimate
        </label>
        {form.applicable ? (
          <>
            <Field label="GST rate %" required hint="The rate that applies to this work. There is no default.">
              <Input
                inputMode="decimal"
                disabled={!edit}
                placeholder="e.g. 18"
                value={form.rate_pct ?? ""}
                onChange={(e) => set("rate_pct", e.target.value || null)}
                className="num text-right"
              />
            </Field>
            <Field label="Supply">
              <Select disabled={!edit} value={form.supply} onChange={(e) => set("supply", e.target.value as GstConfig["supply"])}>
                <option value="intra">Within the state (CGST + SGST)</option>
                <option value="inter">Other state (IGST)</option>
              </Select>
            </Field>
            <Field label="Rates are">
              <Select disabled={!edit} value={form.mode} onChange={(e) => set("mode", e.target.value as GstConfig["mode"])}>
                <option value="exclusive">Without GST (add GST)</option>
                <option value="inclusive">Including GST (show GST only)</option>
              </Select>
            </Field>
            <Field label="GST on">
              <Select disabled={!edit} value={form.base} onChange={(e) => set("base", e.target.value as GstConfig["base"])}>
                <option value="after_charges">Subtotal after charges</option>
                <option value="works_subtotal">Works subtotal only</option>
              </Select>
            </Field>
          </>
        ) : null}
        {edit ? (
          <Button variant="secondary" disabled={!dirty || (form.applicable && !form.rate_pct)} onClick={() => void onSave(form)}>
            Save GST
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
