import Link from "next/link";

import type { Estimate } from "@/lib/api";
import { indianDate, inr } from "@/lib/format";

export function EstimateList({ estimates, showProject }: { estimates: Estimate[]; showProject?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left">
        <thead className="text-xs text-muted uppercase">
          <tr>
            <th className="py-2 pr-3">Estimate</th>
            {showProject ? <th className="py-2 pr-3">Project</th> : null}
            <th className="py-2 pr-3">Version</th>
            <th className="py-2 pr-3 text-right">Items</th>
            <th className="py-2 pr-3 text-right">Works subtotal</th>
            <th className="py-2">Updated</th>
          </tr>
        </thead>
        <tbody>
          {estimates.map((e) => (
            <tr key={e.id} className="border-t border-line">
              <td className="py-2 pr-3">
                <Link href={`/projects/${e.project_id}/estimates/${e.id}`} className="font-medium text-accent hover:underline">
                  {e.title}
                </Link>
                <div className="text-xs text-muted">{e.estimate_number}</div>
              </td>
              {showProject ? <td className="py-2 pr-3">{e.project_name}</td> : null}
              <td className="py-2 pr-3">
                V{e.draft_version_no} draft{e.version_count > 1 ? ` · ${e.version_count - 1} saved` : ""}
              </td>
              <td className="num py-2 pr-3 text-right">{e.item_count}</td>
              <td className="num py-2 pr-3 text-right">{inr(e.works_subtotal)}</td>
              <td className="py-2">{indianDate(e.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
