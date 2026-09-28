"use client";

import { useEffect, useState } from "react";

import { EditableCell } from "@/components/EditableCell";
import { Alert, Button, Input, Select } from "@/components/ui";
import { api, ApiError, del, patch, post, type LeadStatement, type Version } from "@/lib/api";

import type { WorkspaceProps } from "./context";

const CLASSES: [string, string][] = [
  ["earth_sand", "Earth / sand / gravel / murrum"],
  ["aggregate_stone", "Coarse aggregate / rubble / stone"],
  ["cement_steel", "Cement / steel (per tonne)"],
];

/** Lead statement: material, source and distance; charges from the SoR lead table of the zone. */
export function LeadTab({ version, mutate }: WorkspaceProps) {
  const vid = version.version.id;
  const [data, setData] = useState<LeadStatement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ material: "", source: "", material_class: "earth_sand", distance_km: "" });

  useEffect(() => {
    let cancelled = false;
    api<LeadStatement>(`/versions/${vid}/lead-statement`)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the lead statement."));
    return () => {
      cancelled = true;
    };
  }, [vid]);

  async function change(request: () => Promise<LeadStatement>) {
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

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        LEAD STATEMENT — charges from SoR 2026-27 COM-LDLFT-2, Zone {data.zone} (initial lead of 1 km is in the item rate; charges
        include 13.615 %). Changing a distance reprices every item that uses it.
      </p>
      {error ? <Alert>{error}</Alert> : null}
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="w-10 px-2 py-2 text-left">Sl</th>
              <th className="px-2 py-2 text-left">Name of material</th>
              <th className="px-2 py-2 text-left">Name of source</th>
              <th className="w-44 px-2 py-2 text-left">Class</th>
              <th className="w-24 px-2 py-2 text-right">Distance km</th>
              <th className="px-2 py-2 text-left">Working</th>
              <th className="w-28 px-2 py-2 text-right">Total Rs</th>
              {edit ? <th className="w-12" /> : null}
            </tr>
          </thead>
          <tbody>
            {data.entries.map((e, n) => (
              <tr key={e.id} className="border-t border-line align-top">
                <td className="px-2 py-1.5">{n + 1}</td>
                <td>
                  <EditableCell label="Material" value={e.material} editable={edit} onSave={(v) => change(() => patch<LeadStatement>(`/lead-entries/${e.id}`, { material: v }))} />
                </td>
                <td>
                  <EditableCell label="Source" value={e.source} editable={edit} onSave={(v) => change(() => patch<LeadStatement>(`/lead-entries/${e.id}`, { source: v }))} />
                </td>
                <td className="px-1 py-1">
                  <Select
                    aria-label="Material class"
                    disabled={!edit}
                    value={e.material_class}
                    onChange={(ev) => void change(() => patch<LeadStatement>(`/lead-entries/${e.id}`, { material_class: ev.target.value }))}
                    className="px-1 py-1 text-xs"
                  >
                    {CLASSES.map(([k, label]) => (
                      <option key={k} value={k}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </td>
                <td>
                  <EditableCell label="Distance" numeric value={e.distance_km} editable={edit} onSave={(v) => change(() => patch<LeadStatement>(`/lead-entries/${e.id}`, { distance_km: v || null }))} />
                </td>
                <td className="px-2 py-1.5 text-xs text-muted">{e.problem ?? e.working}</td>
                <td className="num px-2 py-1.5 text-right font-medium">{e.amount}</td>
                {edit ? (
                  <td className="px-2 py-1.5 text-right">
                    <button className="text-xs text-bad hover:underline" onClick={() => window.confirm(`Remove ${e.material}?`) && void change(() => del<LeadStatement>(`/lead-entries/${e.id}`))}>
                      ✕
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
            {data.entries.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-2 py-3 text-muted">
                  No materials yet. Add the materials whose quarries are beyond the initial lead.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {edit ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            await change(() => post<LeadStatement>(`/versions/${vid}/lead-entries`, { ...form, distance_km: form.distance_km || null }));
            setForm({ material: "", source: "", material_class: "earth_sand", distance_km: "" });
          }}
        >
          <Input aria-label="Material" placeholder="Material, e.g. Fine Aggregate/ Sand" value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} className="w-64" />
          <Input aria-label="Source" placeholder="Source / quarry" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} className="w-48" />
          <Select aria-label="Class" value={form.material_class} onChange={(e) => setForm({ ...form, material_class: e.target.value })} className="w-56">
            {CLASSES.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </Select>
          <Input aria-label="Distance km" placeholder="km" inputMode="decimal" value={form.distance_km} onChange={(e) => setForm({ ...form, distance_km: e.target.value })} className="num w-24 text-right" />
          <Button type="submit" variant="secondary" disabled={!form.material.trim()}>
            Add material
          </Button>
        </form>
      ) : null}
      <p className="text-xs text-muted">
        Certify in the estimate that the leads are from the nearest approved sources by the shortest route.
      </p>
    </div>
  );
}
