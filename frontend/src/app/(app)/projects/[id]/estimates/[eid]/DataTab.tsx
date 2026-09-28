"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button, Select } from "@/components/ui";
import { api, ApiError, patch, post, type Analysis, type AnalysisRow, type Version } from "@/lib/api";
import { inr } from "@/lib/format";

import type { WorkspaceProps } from "./context";

const SECTIONS = [
  { key: "A", title: "A. MATERIALS" },
  { key: "B", title: "B. MACHINERY" },
  { key: "C", title: "C. LABOUR" },
] as const;

type Adjustment = { kind: string; description: string; quantity: string; rate?: string; lead_key?: string; with_ohp?: boolean };

/** Rate analysis ("data") of one BOQ item, laid out like the department's data sheet. */
export function DataTab({ version, mutate, itemId, onPickItem }: WorkspaceProps & { itemId: string | null; onPickItem: (id: string) => void }) {
  const items = version.sections.flatMap((s) => s.items);
  const current = items.find((i) => i.id === itemId) ?? items[0];
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    api<Analysis>(`/boq-items/${current.id}/analysis`)
      .then((a) => !cancelled && setData(a))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the data sheet."));
    return () => {
      cancelled = true;
    };
  }, [current, version]);

  if (!current) return <p className="text-muted">Add items to the BOQ first.</p>;

  async function change(request: () => Promise<Analysis>) {
    setError(null);
    try {
      setData(await request());
      await mutate(() => api<Version>(`/versions/${version.version.id}`)).catch(() => undefined);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The change could not be saved.");
    }
  }

  const edit = Boolean(data?.can_edit && data.has_analysis);
  const raw = (data?.raw ?? {}) as { deleted_rows?: number[]; adjustments?: Adjustment[] };
  const deleted = new Set(raw.deleted_rows ?? []);
  const adjustments = raw.adjustments ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="data-item" className="text-sm text-muted">
          Item
        </label>
        <Select id="data-item" value={current.id} onChange={(e) => onPickItem(e.target.value)} className="max-w-xl">
          {items.map((i) => (
            <option key={i.id} value={i.id}>
              {i.item_no_display} {i.rate_info?.item_code ? `· ${i.rate_info.item_code}` : ""} — {i.description.slice(0, 70)}
            </option>
          ))}
        </Select>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {!data ? <p className="text-muted">Loading…</p> : null}
      {data && !data.has_analysis ? (
        <Alert tone="info">
          {data.code ? (
            <>
              {data.code}: rate {inr(data.book_rate)} as printed in the Standard Data.{" "}
              {data.book_status === "unverified" || data.book_status === "none"
                ? `Its data sheet could not be rebuilt from the book${data.book_note ? ` (${data.book_note})` : ""}, so the printed rate is used. Check it against the book.`
                : "Pick the rate again to attach its data sheet."}
            </>
          ) : (
            "This item has a rate typed by hand. Pick a Standard Data rate on the BOQ (“pick rate”) to get its data sheet."
          )}
        </Alert>
      ) : null}
      {data?.has_analysis ? (
        <div className="space-y-4 rounded border border-line bg-surface p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="font-semibold">{data.code}</div>
              <p className="max-w-3xl text-sm text-muted">{data.item_description}</p>
            </div>
            <div className="flex flex-wrap gap-1">
              <Badge tone={data.status === "verified" ? "ok" : "warn"}>
                {data.status === "verified" ? "Book data, recomputed" : data.status === "rounded" ? "Book data (book rounds differently)" : "Edited"}
              </Badge>
              <Badge>Book rate {inr(data.book_rate)}</Badge>
            </div>
          </div>
          <div className="text-sm font-medium">
            DATA: RATE ANALYSIS — UNIT: {data.analysis_qty} {data.analysis_unit}
          </div>
          {SECTIONS.map((s) => (
            <SectionTable
              key={s.key}
              title={s.title}
              rows={data.rows.filter((r) => r.section === s.key)}
              total={s.key === "A" ? data.materials : s.key === "B" ? data.machinery : data.labour}
              edit={edit}
              onToggle={(row) => {
                const next = new Set(deleted);
                if (next.has(row.index)) next.delete(row.index);
                else next.add(row.index);
                void change(() => patch<Analysis>(`/boq-items/${data.item_id}/analysis`, { deleted_rows: [...next].sort((a, b) => a - b) }));
              }}
            />
          ))}
          <div className="text-sm">
            labour component / unit qty {data.labour_per_unit}; with contractor&apos;s profit and overheads {data.labour_per_unit_with_ohp}
          </div>

          <table className="w-full max-w-2xl text-sm">
            <tbody>
              <Line label="A. Cost of Materials" value={data.materials} />
              <Line label="B. Hire charges of Machinery" value={data.machinery} />
              <Line label="C. Cost of Labour" value={data.labour} />
              {data.additions.map((a) => (
                <Line key={a.description} label={`Add ${a.description} @ ${a.pct} %`} value={a.amount} />
              ))}
              <Line label={`D. Add for contractor's profit and overheads @ ${data.ohp_pct} %`} value={data.ohp} />
              {data.extras.map((x) => (
                <Line key={x.description} label={x.description} value={x.amount} />
              ))}
              <Line label={`Total cost for ${data.analysis_qty} ${data.analysis_unit}`} value={data.total} strong />
              <Line label={`Rate per ${data.analysis_unit} (A+B+C+D)/${data.analysis_qty}`} value={data.rate_before_adjustments} strong />
              {data.adjustments.map((a, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1 pr-2">
                    {a.description}: {a.quantity} × {a.rate}
                    {edit ? (
                      <button
                        className="ml-2 text-xs text-bad hover:underline"
                        onClick={() =>
                          void change(() =>
                            patch<Analysis>(`/boq-items/${data.item_id}/analysis`, { adjustments: adjustments.filter((_, j) => j !== i) }),
                          )
                        }
                      >
                        remove
                      </button>
                    ) : null}
                  </td>
                  <td className="num py-1 text-right">{a.amount}</td>
                </tr>
              ))}
              <Line label="Rate per unit" value={data.rate_exact} />
              <Line label="Or say Rs." value={data.rate} strong />
            </tbody>
          </table>

          {edit ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                disabled={data.lead_options.length === 0}
                title={data.lead_options.length === 0 ? "Add materials to the Lead statement first" : undefined}
                onClick={() => void change(() => post<Analysis>(`/boq-items/${data.item_id}/analysis/auto-conveyance`))}
              >
                Add conveyance from lead statement
              </Button>
              <CementCorrection onAdd={(a) => void change(() => patch<Analysis>(`/boq-items/${data.item_id}/analysis`, { adjustments: [...adjustments, a] }))} />
            </div>
          ) : null}
          <p className="text-xs text-muted">
            Tick “omit” to delete a component the work does not need (Standard Data, Annexure-A 5). The BOQ rate is the “Or say” rate.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function SectionTable({ title, rows, total, edit, onToggle }: { title: string; rows: AnalysisRow[]; total: string | null | undefined; edit: boolean; onToggle: (row: AnalysisRow) => void }) {
  return (
    <div>
      <div className="mb-1 text-sm font-medium">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="bg-panel text-xs text-muted">
            <tr>
              <th className="px-2 py-1 text-left">Particulars</th>
              <th className="w-16 px-2 py-1 text-left">Unit</th>
              <th className="w-24 px-2 py-1 text-right">Quantity</th>
              <th className="w-24 px-2 py-1 text-right">Rate</th>
              <th className="w-28 px-2 py-1 text-right">Amount</th>
              {edit ? <th className="w-16 px-2 py-1">Omit</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-2 py-1 text-muted">
                  NIL
                </td>
              </tr>
            ) : null}
            {rows.map((r) => (
              <tr key={r.index} className={`border-t border-line ${r.deleted ? "text-muted line-through" : ""}`}>
                <td className="px-2 py-1">{r.description}</td>
                <td className="px-2 py-1">{r.unit}</td>
                <td className="num px-2 py-1 text-right">{r.pct ? `${r.pct} %` : r.quantity}</td>
                <td className="num px-2 py-1 text-right">{r.pct ? "" : r.rate}</td>
                <td className="num px-2 py-1 text-right">{r.amount}</td>
                {edit ? (
                  <td className="px-2 py-1 text-center">
                    <input type="checkbox" aria-label={`Omit ${r.description}`} checked={r.deleted} onChange={() => onToggle(r)} />
                  </td>
                ) : null}
              </tr>
            ))}
            <tr className="border-t border-line font-medium">
              <td colSpan={4} className="px-2 py-1 text-right">
                Total
              </td>
              <td className="num px-2 py-1 text-right">{total}</td>
              {edit ? <td /> : null}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Line({ label, value, strong }: { label: string; value: string | null | undefined; strong?: boolean }) {
  return (
    <tr className={`border-t border-line ${strong ? "font-semibold" : ""}`}>
      <td className="py-1 pr-2">{label}</td>
      <td className="num py-1 text-right">{value}</td>
    </tr>
  );
}

function CementCorrection({ onAdd }: { onAdd: (a: Adjustment) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ quantity: "", present: "", ssr: "5.10" });
  if (!open)
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Add cement / steel rate correction
      </Button>
    );
  const diff = Number(form.present) - Number(form.ssr);
  return (
    <form
      className="flex flex-wrap items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onAdd({
          kind: "correction",
          description: `Correction for cement rate (present ${form.present}, SSR ${form.ssr})`,
          quantity: form.quantity,
          rate: diff.toFixed(4),
          with_ohp: true,
        });
        setOpen(false);
      }}
    >
      <label className="flex flex-col">
        kg per unit
        <input className="w-24 rounded border border-line px-2 py-1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
      </label>
      <label className="flex flex-col">
        Present rate / kg
        <input className="w-24 rounded border border-line px-2 py-1" value={form.present} onChange={(e) => setForm({ ...form, present: e.target.value })} />
      </label>
      <label className="flex flex-col">
        SSR rate / kg
        <input className="w-24 rounded border border-line px-2 py-1" value={form.ssr} onChange={(e) => setForm({ ...form, ssr: e.target.value })} />
      </label>
      <Button type="submit" disabled={!form.quantity || !form.present || Number.isNaN(diff)}>
        Add
      </Button>
    </form>
  );
}
