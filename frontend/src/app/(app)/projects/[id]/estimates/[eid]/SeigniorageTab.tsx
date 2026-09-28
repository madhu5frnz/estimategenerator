"use client";

import { useEffect, useState } from "react";

import { EditableCell } from "@/components/EditableCell";
import { Alert, Button, Select } from "@/components/ui";
import { api, ApiError, del, patch, post, type Seigniorage, type Version } from "@/lib/api";
import { inr } from "@/lib/format";

import type { WorkspaceProps } from "./context";

const MATERIALS: Record<string, string> = {
  metal: "Metal",
  sand: "Sand",
  m_sand: "M-Sand",
  earth: "Earth / gravel",
  stone: "Stone (MT)",
};

export function SeigniorageTab({ version, mutate }: WorkspaceProps) {
  const vid = version.version.id;
  const [data, setData] = useState<Seigniorage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = version.sections.flatMap((s) => s.items);
  const byKey = new Map(items.map((i) => [i.line_key, i]));

  useEffect(() => {
    let cancelled = false;
    api<Seigniorage>(`/versions/${vid}/seigniorage`)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load seigniorage."));
    return () => {
      cancelled = true;
    };
  }, [vid, version]);

  async function change(request: () => Promise<Seigniorage>) {
    setError(null);
    try {
      setData(await request());
      await mutate(() => api<Version>(`/versions/${vid}`)).catch(() => undefined);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The change could not be saved.");
    }
  }

  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const edit = data.can_edit;
  const s = data.settings as { dmf_pct: string; smet_pct: string; permit_fee_pct: string; permit_fee_materials: string[] };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          SEIGNIORAGE CHARGES — quantity × material per unit × rate. Rates: {data.note}.
        </p>
        {edit ? (
          <Button variant="secondary" onClick={() => void change(() => post<Seigniorage>(`/versions/${vid}/seigniorage/suggest`))}>
            Suggest from items
          </Button>
        ) : null}
      </div>
      {error ? <Alert>{error}</Alert> : null}
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="px-2 py-2 text-left">Item of work</th>
              <th className="w-32 px-2 py-2 text-left">Material</th>
              <th className="w-28 px-2 py-2 text-right">Qty</th>
              <th className="w-24 px-2 py-2 text-right">Coefficient</th>
              <th className="w-24 px-2 py-2 text-right">Material qty</th>
              <th className="w-20 px-2 py-2 text-right">Rate</th>
              <th className="w-28 px-2 py-2 text-right">Amount</th>
              {edit ? <th className="w-10" /> : null}
            </tr>
          </thead>
          <tbody>
            {data.lines.map((l) => {
              const item = l.boq_item_line_key ? byKey.get(l.boq_item_line_key) : undefined;
              return (
                <tr key={l.id} className="border-t border-line align-top">
                  <td className="px-2 py-1.5">
                    {l.label} {item ? <span className="text-xs text-muted">{item.description.slice(0, 50)}</span> : null}
                  </td>
                  <td className="px-1 py-1">
                    <Select aria-label="Material" disabled={!edit} value={l.material} className="px-1 py-1 text-xs"
                      onChange={(e) => void change(() => patch<Seigniorage>(`/seigniorage-lines/${l.id}`, { material: e.target.value }))}>
                      {Object.entries(MATERIALS).map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td>
                    {l.follows_item ? (
                      <div className="num px-2 py-1.5 text-right" title="Follows the item quantity">
                        {l.item_quantity} <span className="text-xs text-accent">ƒ</span>
                      </div>
                    ) : (
                      <EditableCell label="Quantity" numeric value={l.item_quantity} editable={edit}
                        onSave={(v) => change(() => patch<Seigniorage>(`/seigniorage-lines/${l.id}`, { item_quantity: v }))} />
                    )}
                  </td>
                  <td>
                    <EditableCell label="Coefficient" numeric value={l.factor} editable={edit}
                      onSave={(v) => change(() => patch<Seigniorage>(`/seigniorage-lines/${l.id}`, { factor: v }))} />
                  </td>
                  <td className="num px-2 py-1.5 text-right">{l.material_quantity}</td>
                  <td>
                    <EditableCell label="Rate" numeric value={l.rate} editable={edit}
                      onSave={(v) => change(() => patch<Seigniorage>(`/seigniorage-lines/${l.id}`, { rate: v }))} />
                  </td>
                  <td className="num px-2 py-1.5 text-right">{l.amount}</td>
                  {edit ? (
                    <td className="px-2 py-1.5 text-right">
                      <button className="text-xs text-bad hover:underline" aria-label="Remove line"
                        onClick={() => void change(() => del<Seigniorage>(`/seigniorage-lines/${l.id}`))}>
                        ✕
                      </button>
                    </td>
                  ) : null}
                </tr>
              );
            })}
            {data.lines.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-2 py-3 text-muted">
                  No lines yet. “Suggest from items” proposes metal and sand for concrete items (from the mix in the item) and earth
                  for embankments.
                </td>
              </tr>
            ) : null}
          </tbody>
          <tfoot className="border-t-2 border-line bg-panel text-sm">
            <Row label="Total seigniorage" value={data.total} />
            <Row label={`DMF @ ${s.dmf_pct} %`} value={data.dmf} />
            <Row label={`SMET @ ${s.smet_pct} %`} value={data.smet} />
            <Row label={`Permit fee @ ${s.permit_fee_pct} % on ${s.permit_fee_materials.map((m) => MATERIALS[m] ?? m).join(", ")}`} value={data.permit_fee} />
          </tfoot>
        </table>
      </div>
      <p className="text-xs text-muted">Rates and percentages can be changed in General Abstract → Settings.</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td colSpan={6} className="px-2 py-1.5 text-right">
        {label}
      </td>
      <td className="num px-2 py-1.5 text-right font-medium">{inr(value).slice(1)}</td>
      <td />
    </tr>
  );
}
