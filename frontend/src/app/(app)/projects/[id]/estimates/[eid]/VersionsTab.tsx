"use client";

import { Badge } from "@/components/ui";
import type { VersionSummary } from "@/lib/api";
import { indianDate, inr } from "@/lib/format";

export function VersionsTab({ versions, currentId, onOpen }: { versions: VersionSummary[]; currentId: string; onOpen: (id: string) => void }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Saving a version keeps it exactly as it is (read-only). You then continue in the next draft. Side-by-side comparison arrives in
        Phase 2.
      </p>
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[640px] text-left">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="px-3 py-2">Version</th>
              <th className="px-3 py-2">Note</th>
              <th className="px-3 py-2">Saved</th>
              <th className="px-3 py-2 text-right">Works subtotal</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id} className="border-t border-line">
                <td className="px-3 py-2 font-medium">
                  V{v.version_no} <Badge tone={v.status === "draft" ? "accent" : "neutral"}>{v.status === "draft" ? "Draft" : "Frozen"}</Badge>
                </td>
                <td className="px-3 py-2">{v.change_note ?? "—"}</td>
                <td className="px-3 py-2">{v.frozen_at ? indianDate(v.frozen_at) : "—"}</td>
                <td className="num px-3 py-2 text-right">{inr(v.works_subtotal)}</td>
                <td className="px-3 py-2 text-right">
                  {v.id === currentId ? (
                    <span className="text-xs text-muted">Showing</span>
                  ) : (
                    <button className="text-accent hover:underline" onClick={() => onOpen(v.id)}>
                      Open
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
