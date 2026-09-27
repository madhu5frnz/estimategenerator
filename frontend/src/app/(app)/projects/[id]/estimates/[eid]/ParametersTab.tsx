"use client";

import { useState } from "react";

import { EditableCell } from "@/components/EditableCell";
import { Badge, Button, Input, Select } from "@/components/ui";
import { del, patch, post, type Version } from "@/lib/api";

import type { WorkspaceProps } from "./context";

const PROVENANCE: Record<string, string> = {
  user_entered: "Entered",
  ai_extracted: "AI-extracted",
  rule_extracted: "Parsed from text",
  default_accepted: "Default accepted",
  document_extracted: "From document",
};

/** "GSB thickness" → "gsb_thickness" */
function toName(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 63);
  return /^[a-z]/.test(slug) ? slug : slug ? `p_${slug}`.slice(0, 63) : "";
}

export function ParametersTab({ version, mutate, units, editable }: WorkspaceProps) {
  const vid = version.version.id;
  const formulaUnits = units.filter((u) => !["lump_sum", "other"].includes(u.dimension));
  const [form, setForm] = useState({ label: "", value: "", unit: "m" });
  const [busy, setBusy] = useState(false);

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">
        Named values such as road length or carriageway width. Formula lines can use them, and changing a value here recalculates every
        line that uses it.
      </p>
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[720px] text-left">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="px-2 py-2">Parameter</th>
              <th className="px-2 py-2">Name in formulas</th>
              <th className="w-36 px-2 py-2 text-right">Value</th>
              <th className="w-28 px-2 py-2">Unit</th>
              <th className="w-28 px-2 py-2">Source</th>
              <th className="w-24 px-2 py-2 text-right">Used by</th>
              {editable ? <th className="w-16" aria-label="Actions" /> : null}
            </tr>
          </thead>
          <tbody>
            {version.parameters.map((p) => (
              <tr key={p.id} className="border-t border-line">
                <td>
                  <EditableCell label="Label" value={p.label} editable={editable} onSave={(label) => mutate(() => patch<Version>(`/parameters/${p.id}`, { label }))} />
                </td>
                <td className="px-2 py-1.5 font-mono text-xs">{p.name}</td>
                <td>
                  <EditableCell
                    label={`${p.label} value`}
                    value={p.value}
                    numeric
                    editable={editable}
                    placeholder="missing"
                    className={p.value === null ? "text-bad" : ""}
                    onSave={(value) => mutate(() => patch<Version>(`/parameters/${p.id}`, { value: value.trim() === "" ? null : value }))}
                  />
                </td>
                <td className="px-1 py-1">
                  {editable ? (
                    <Select
                      aria-label={`${p.label} unit`}
                      value={p.unit ?? ""}
                      onChange={(e) => void mutate(() => patch<Version>(`/parameters/${p.id}`, { unit: e.target.value || null })).catch(() => undefined)}
                      className="w-24 px-1 py-1"
                    >
                      <option value="">(number)</option>
                      {formulaUnits.map((u) => (
                        <option key={u.code} value={u.code}>
                          {u.display_name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <div className="px-2 py-1.5">{p.unit_display ?? "—"}</div>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  <Badge tone={p.provenance === "user_entered" ? "neutral" : "warn"}>{PROVENANCE[p.provenance] ?? p.provenance}</Badge>
                </td>
                <td className="num px-2 py-1.5 text-right">{p.used_by ? `${p.used_by} line(s)` : "—"}</td>
                {editable ? (
                  <td className="px-2 text-right">
                    <button
                      className="text-xs text-bad hover:underline disabled:text-muted disabled:no-underline"
                      disabled={p.used_by > 0}
                      title={p.used_by ? "Used by measurement lines" : "Delete"}
                      onClick={() => void mutate(() => del<Version>(`/parameters/${p.id}`)).catch(() => undefined)}
                    >
                      Delete
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
            {!version.parameters.length ? (
              <tr>
                <td colSpan={7} className="px-2 py-4 text-center text-muted">
                  No parameters yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {editable ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await mutate(() =>
                post<Version>(`/versions/${vid}/parameters`, {
                  name: toName(form.label),
                  label: form.label,
                  value: form.value || null,
                  unit: form.unit || null,
                }),
              );
              setForm({ label: "", value: "", unit: form.unit });
            } catch {
              // shown by the workspace
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input aria-label="New parameter label" placeholder="New parameter, e.g. Road length" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} className="w-64 py-1" />
          <span className="font-mono text-xs text-muted">{toName(form.label) || "name"}</span>
          <Input aria-label="New parameter value" placeholder="Value" inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} className="num w-28 py-1 text-right" />
          <Select aria-label="New parameter unit" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} className="w-24 px-1 py-1">
            <option value="">(number)</option>
            {formulaUnits.map((u) => (
              <option key={u.code} value={u.code}>
                {u.display_name}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="secondary" className="py-1" disabled={busy || !toName(form.label)}>
            Add parameter
          </Button>
        </form>
      ) : null}
    </div>
  );
}
