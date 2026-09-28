"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button, Field, Input, Textarea } from "@/components/ui";
import { api, ApiError, patch, type Docket } from "@/lib/api";
import { inr } from "@/lib/format";

import type { WorkspaceProps } from "./context";

/** Loads the docket (cover, check slip, certificates, quotations) of a version. */
function useDocket(version: WorkspaceProps["version"]) {
  const vid = version.version.id;
  const [data, setData] = useState<Docket | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api<Docket>(`/versions/${vid}/docket`)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the docket."));
    return () => {
      cancelled = true;
    };
  }, [vid, version]);
  async function save(body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try {
      setData(await patch<Docket>(`/versions/${vid}/docket`, body));
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save.");
      return false;
    }
  }
  return { data, error, save };
}

/** The printed page: a white sheet with the name of work at the top. */
function Paper({ title, nameOfWork, children }: { title: string; nameOfWork: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-4xl rounded-lg border border-line bg-surface p-6 shadow-sm md:p-10">
      <h2 className="text-center font-serif text-2xl font-bold tracking-[0.12em] uppercase">{title}</h2>
      {nameOfWork ? <p className="mt-3 text-center font-semibold text-accent">Name of Work: {nameOfWork}</p> : null}
      <hr className="my-6 border-ink/70" />
      {children}
    </div>
  );
}

function Signatories({ names }: { names: string[] }) {
  return (
    <div className="mt-12 grid gap-6 text-center text-sm" style={{ gridTemplateColumns: `repeat(${Math.max(names.length, 1)}, minmax(0, 1fr))` }}>
      {names.map((n) => (
        <div key={n}>
          <div className="mx-auto mb-2 h-10 w-40 border-b border-line" />
          {n}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ cover
const COVER_FIELDS: [string, string][] = [
  ["name_of_work", "Name of work"],
  ["project", "Project"],
  ["circle", "Circle"],
  ["division", "Division"],
  ["sub_division", "Sub-division"],
  ["village", "Village"],
  ["mandal", "Mandal"],
  ["district", "District"],
];

export function CoverSheet({ version }: WorkspaceProps) {
  const { data, error, save } = useDocket(version);
  const [form, setForm] = useState<Record<string, string> | null>(null);
  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const cover = form ?? (data.cover as Record<string, string>);
  const name = cover.name_of_work || version.estimate.title;
  return (
    <div className="space-y-6">
      {error ? <Alert>{error}</Alert> : null}
      <div className="mx-auto flex max-w-4xl flex-col items-center gap-6 rounded-lg border border-line bg-surface px-6 py-16 text-center shadow-sm">
        <div className="font-serif text-3xl font-bold tracking-[0.15em]">GOVERNMENT OF TELANGANA</div>
        <div className="text-lg font-semibold tracking-[0.2em] uppercase">{cover.department || "Irrigation & CAD Department"}</div>
        <div className="text-sm text-muted">{[cover.circle, cover.division, cover.sub_division].filter(Boolean).join(" · ")}</div>
        <div className="mt-6 text-sm font-semibold tracking-[0.2em] uppercase">Name of Work</div>
        <p className="max-w-2xl font-serif text-xl leading-relaxed">{name}</p>
        <div className="mt-6 text-sm font-semibold tracking-[0.2em] uppercase">Amount of Estimate</div>
        <div className="font-serif text-3xl font-bold">Rs {data.amount_in_lakhs} Lakhs</div>
        <div className="text-sm text-muted">
          {data.amount_display} · {data.amount_in_words}
        </div>
        <div className="mt-4 text-xs text-muted">
          {version.estimate.estimate_number} · SSR {data.ssr_year} · V{data.version_no}
        </div>
      </div>
      {data.can_edit ? (
        <form
          className="no-print mx-auto grid max-w-4xl gap-3 rounded-lg border border-line bg-surface p-4 sm:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await save({ cover })) setForm(null);
          }}
        >
          {COVER_FIELDS.map(([k, label]) =>
            k === "name_of_work" ? (
              <Field key={k} label={label} className="sm:col-span-2">
                <Textarea rows={3} value={cover[k] ?? ""} onChange={(e) => setForm({ ...cover, [k]: e.target.value })} />
              </Field>
            ) : (
              <Field key={k} label={label}>
                <Input value={cover[k] ?? ""} onChange={(e) => setForm({ ...cover, [k]: e.target.value })} />
              </Field>
            ),
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={!form}>
              Save cover page
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------- check slip
export function CheckSlipSheet({ version }: WorkspaceProps) {
  const { data, error, save } = useDocket(version);
  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const name = (data.cover as Record<string, string>).name_of_work || version.estimate.title;
  return (
    <Paper title="Check slip accompanying the project / scheme / work estimate" nameOfWork={name}>
      {error ? <Alert>{error}</Alert> : null}
      <table className="w-full text-sm">
        <tbody>
          {data.check_slip.map((row) => (
            <tr key={row.no} className="border-b border-line align-top">
              <td className="w-16 py-2 pr-2 font-medium">{row.no}</td>
              <td className="py-2 pr-2">{row.question}</td>
              <td className="w-4 py-2">:</td>
              <td className="w-72 py-1">
                {data.can_edit ? (
                  <input
                    aria-label={`Answer to ${row.no}`}
                    defaultValue={row.answer}
                    placeholder={row.auto ? "" : "—"}
                    onBlur={(e) => e.target.value !== row.answer && void save({ check_slip: { [row.no]: e.target.value } })}
                    className="w-full rounded border border-transparent bg-transparent px-2 py-1 hover:border-line focus:border-accent focus:outline-none"
                  />
                ) : (
                  <span className="px-2">{row.answer || "—"}</span>
                )}
                {row.auto ? <span className="no-print ml-2 text-[10px] text-muted">auto</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Signatories names={data.signatories} />
    </Paper>
  );
}

// ----------------------------------------------------------- certificates
export function CertificatesSheet({ version }: WorkspaceProps) {
  const { data, error, save } = useDocket(version);
  const [draft, setDraft] = useState<string[] | null>(null);
  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const certs = draft ?? data.certificates;
  const name = (data.cover as Record<string, string>).name_of_work || version.estimate.title;
  return (
    <Paper title="Certificates" nameOfWork={name}>
      {error ? <Alert>{error}</Alert> : null}
      <ol className="space-y-5">
        {certs.map((c, i) => (
          <li key={i} className="flex gap-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-panel text-sm font-semibold">{i + 1}</span>
            {data.can_edit && draft ? (
              <div className="flex-1">
                <Textarea rows={2} value={c} onChange={(e) => setDraft(certs.map((x, j) => (j === i ? e.target.value : x)))} />
                <button className="mt-1 text-xs text-bad hover:underline" onClick={() => setDraft(certs.filter((_, j) => j !== i))}>
                  remove
                </button>
              </div>
            ) : (
              <p className="flex-1 leading-relaxed">{c}</p>
            )}
          </li>
        ))}
      </ol>
      {data.can_edit ? (
        <div className="no-print mt-6 flex gap-2">
          {draft ? (
            <>
              <Button variant="secondary" onClick={() => setDraft([...certs, "Certified that "])}>
                Add certificate
              </Button>
              <Button onClick={async () => (await save({ certificates: certs })) && setDraft(null)}>Save certificates</Button>
              <Button variant="ghost" onClick={() => setDraft(null)}>
                Cancel
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setDraft(data.certificates)}>
              Edit certificates
            </Button>
          )}
        </div>
      ) : null}
      <Signatories names={data.signatories} />
    </Paper>
  );
}

// ------------------------------------------------------------- quotations
export function QuotationsSheet({ version }: WorkspaceProps) {
  const { data, error, save } = useDocket(version);
  if (!data) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;
  const name = (data.cover as Record<string, string>).name_of_work || version.estimate.title;
  return (
    <Paper title="Quotations / Non-SOR items" nameOfWork={name}>
      {error ? <Alert>{error}</Alert> : null}
      <p className="mb-4 text-sm text-muted">
        Items whose rate is not taken from the Standard Data / SoR. Record the quotation or reference for each; the check slip
        (point 21) follows this list.
      </p>
      {data.quotations.length === 0 ? (
        <Alert tone="ok">All items are priced from the Standard Data / SoR. No quotations are needed.</Alert>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-panel text-xs text-muted uppercase">
              <tr>
                <th className="px-2 py-2 text-left">Sl</th>
                <th className="px-2 py-2 text-left">Item</th>
                <th className="px-2 py-2 text-right">Rate</th>
                <th className="px-2 py-2 text-left">Supplier / source</th>
                <th className="px-2 py-2 text-left">Quotation / reference</th>
                <th className="px-2 py-2 text-left">Remarks</th>
              </tr>
            </thead>
            <tbody>
              {data.quotations.map((q) => (
                <tr key={q.line_key} className="border-t border-line align-top">
                  <td className="px-2 py-2">{q.sl_no}</td>
                  <td className="px-2 py-2">
                    {q.description}
                    <div className="text-xs text-muted">
                      {q.quantity} {q.unit}
                    </div>
                  </td>
                  <td className="num px-2 py-2 text-right">{q.rate ? inr(q.rate) : "—"}</td>
                  {(["supplier", "reference", "note"] as const).map((k) => (
                    <td key={k} className="px-1 py-1">
                      {data.can_edit ? (
                        <input
                          aria-label={`${k} for ${q.description}`}
                          defaultValue={q[k]}
                          onBlur={(e) =>
                            e.target.value !== q[k] &&
                            void save({ quotations: { [q.line_key]: { supplier: q.supplier, reference: q.reference, note: q.note, [k]: e.target.value } } })
                          }
                          className="w-full rounded border border-line bg-transparent px-2 py-1"
                        />
                      ) : (
                        q[k] || "—"
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4">
        <Badge tone={data.quotations.length ? "warn" : "ok"}>{data.quotations.length} non-SOR item(s)</Badge>
      </div>
    </Paper>
  );
}
