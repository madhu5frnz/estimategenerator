"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Button, ButtonLink, Input, Select, StatusBadge } from "@/components/ui";
import { api, apiRaw, ApiError, type Option, type Project } from "@/lib/api";
import { indianDate, inr, STATUS_LABELS } from "@/lib/format";

const PAGE_SIZE = 25;

export function ProjectList() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);

  const [search, setSearch] = useState(q);
  const [types, setTypes] = useState<Option[]>([]);
  const [rows, setRows] = useState<Project[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in changes)) next.delete("page");
    router.replace(`${pathname}?${next.toString()}`);
  };

  useEffect(() => {
    api<Option[]>("/project-types").then(setTypes).catch(() => setTypes([]));
  }, []);

  // Debounced search box → URL (so filters survive reloads and can be shared).
  useEffect(() => {
    if (search === q) return;
    const timer = setTimeout(() => update({ q: search.trim() }), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => {
    const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (q) query.set("q", q);
    if (type) query.set("type", type);
    if (status) query.set("status", status);
    let cancelled = false;
    apiRaw<Project[]>(`/projects?${query.toString()}`)
      .then(({ data, meta }) => {
        if (cancelled) return;
        setRows(data);
        setTotal(Number(meta.total ?? data.length));
        setError(null);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load projects."));
    return () => {
      cancelled = true;
    };
  }, [q, type, status, page]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(q || type || status);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Projects</h1>
        <ButtonLink href="/projects/new">New project</ButtonLink>
      </div>

      <div className="flex flex-wrap gap-2">
        <Input
          type="search"
          placeholder="Search name, reference, location, district"
          aria-label="Search projects"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <Select aria-label="Project type" value={type} onChange={(e) => update({ type: e.target.value })} className="w-auto">
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t.code} value={t.code}>
              {t.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Status" value={status} onChange={(e) => update({ status: e.target.value })} className="w-auto">
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      {error ? <Alert>{error}</Alert> : null}
      {rows === null ? (
        <p className="text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="rounded border border-dashed border-line p-8 text-center text-muted">
          {filtered ? "No projects match these filters." : "No projects yet."}
          {!filtered ? (
            <div className="mt-3">
              <ButtonLink href="/projects/new">Create your first project</ButtonLink>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="overflow-x-auto rounded border border-line">
          <table className="w-full min-w-[720px] text-left">
            <thead className="bg-panel text-xs text-muted uppercase">
              <tr>
                <th className="px-3 py-2">Project</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">District / State</th>
                <th className="px-3 py-2 text-right">Est. value</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-t border-line hover:bg-panel/60">
                  <td className="px-3 py-2">
                    <Link href={`/projects/${p.id}`} className="font-medium text-accent hover:underline">
                      {p.name}
                    </Link>
                    {p.reference_number ? <div className="text-xs text-muted">{p.reference_number}</div> : null}
                  </td>
                  <td className="px-3 py-2">{p.project_type_label}</td>
                  <td className="px-3 py-2">{[p.district, p.state].filter(Boolean).join(", ")}</td>
                  <td className="num px-3 py-2 text-right">{inr(p.estimated_value)}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="px-3 py-2">{indianDate(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 ? (
        <div className="flex items-center justify-end gap-2 text-xs">
          <span className="text-muted">
            Page {page} of {pages} · {total} projects
          </span>
          <Button variant="secondary" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
            Previous
          </Button>
          <Button variant="secondary" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}
