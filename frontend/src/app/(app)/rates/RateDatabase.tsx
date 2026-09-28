"use client";

import { useCallback, useEffect, useState } from "react";

import { Modal } from "@/components/Modal";
import { useSession } from "@/components/Session";
import { Alert, Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError, del, patch, post, type RateItem, type RateSearch, type RateSource, type Unit } from "@/lib/api";
import { indianDate } from "@/lib/format";

import { sortUnits } from "../projects/[id]/estimates/[eid]/context";

type ItemForm = { item_code: string; description: string; unit: string; rate: string };
const PAGE = 50;

export function RateDatabase() {
  const { me } = useSession();
  const admin = ["owner", "admin"].includes(me.organization.role);
  const [sources, setSources] = useState<RateSource[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [q, setQ] = useState("");
  const [unit, setUnit] = useState("");
  const [expired, setExpired] = useState(false);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<RateSearch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addingSource, setAddingSource] = useState(false);
  const [editing, setEditing] = useState<RateItem | "new" | null>(null);
  const [reload, setReload] = useState(0);

  const loadSources = useCallback(() => api<RateSource[]>("/rate-sources").then(setSources), []);
  useEffect(() => {
    loadSources().catch(() => setError("Could not load the rate sources."));
    api<Unit[]>("/units").then((u) => setUnits(sortUnits(u))).catch(() => undefined);
  }, [loadSources]);

  useEffect(() => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (q.trim()) params.set("q", q.trim());
    if (sourceId) params.set("source_id", sourceId);
    if (unit) params.set("unit", unit);
    if (expired) params.set("include_expired", "true");
    let cancelled = false;
    const timer = setTimeout(() => {
      api<RateSearch>(`/rate-items?${params.toString()}`)
        .then((r) => !cancelled && setResult(r))
        .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Search failed."));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q, sourceId, unit, expired, offset, reload]);

  const selected = sources.find((s) => s.id === sourceId);
  const refresh = async () => {
    setReload((n) => n + 1);
    await loadSources();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Rate Database</h1>
          <p className="text-muted">Rates you pick for BOQ items. An estimate keeps a copy of each rate it uses.</p>
        </div>
        {admin ? (
          <Button variant="secondary" onClick={() => setAddingSource(true)}>
            Add rate source
          </Button>
        ) : null}
      </div>
      {error ? <Alert>{error}</Alert> : null}
      <Alert tone="warn">
        The demo rates are for trying the app. They are <strong>not an official Schedule of Rates</strong>. Use the rates
        your department has published for real estimates.
      </Alert>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sources.map((s) => (
          <button
            key={s.id}
            onClick={() => {
              setSourceId(s.id === sourceId ? "" : s.id);
              setOffset(0);
            }}
            aria-pressed={s.id === sourceId}
            className={`rounded border p-3 text-left hover:border-accent ${s.id === sourceId ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
          >
            <div className="font-medium">
              {s.sor_name} {s.year}
            </div>
            <div className="text-xs text-muted">
              {s.state} · {s.department} · {indianDate(s.effective_from)} to {s.effective_to ? indianDate(s.effective_to) : "open"}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {s.is_demo ? <Badge tone="warn">Demo · not official SOR</Badge> : null}
              {s.owned ? <Badge tone="accent">Your workspace</Badge> : null}
              {s.verification_status === "user_entered" ? <Badge>Entered by you</Badge> : null}
              {s.verification_status === "imported_unverified" ? <Badge tone="warn">Imported from the book · verify</Badge> : null}
              {s.is_expired ? <Badge tone="warn">Expired</Badge> : null}
              <Badge>{s.item_count} items</Badge>
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Search">
          <Input
            placeholder="Description or item code"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            className="w-72"
          />
        </Field>
        <Field label="Unit">
          <Select
            value={unit}
            onChange={(e) => {
              setUnit(e.target.value);
              setOffset(0);
            }}
            className="w-32"
          >
            <option value="">Any</option>
            {units.map((u) => (
              <option key={u.code} value={u.code}>
                {u.display_name}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input type="checkbox" checked={expired} onChange={(e) => setExpired(e.target.checked)} />
          Include expired sources
        </label>
        {selected?.can_edit ? (
          <Button className="mb-0.5" onClick={() => setEditing("new")}>
            Add item to {selected.sor_name}
          </Button>
        ) : null}
      </div>
      {selected && !selected.owned ? (
        <p className="text-xs text-muted">This source comes with the app and is read-only. Add your own source to enter rates.</p>
      ) : null}

      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[760px] text-left">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="w-28 px-2 py-2">Code</th>
              <th className="px-2 py-2">Description</th>
              <th className="w-20 px-2 py-2">Unit</th>
              <th className="w-32 px-2 py-2 text-right">Rate</th>
              <th className="w-56 px-2 py-2">Source</th>
              <th className="w-28 px-2 py-2" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {result?.items.map((r) => (
              <tr key={r.id} className="border-t border-line align-top">
                <td className="px-2 py-1.5 font-mono text-xs">{r.item_code}</td>
                <td className="px-2 py-1.5">{r.description}</td>
                <td className="px-2 py-1.5">{r.unit_display}</td>
                <td className="num px-2 py-1.5 text-right">{r.rate_display}</td>
                <td className="px-2 py-1.5 text-xs">
                  {r.source_label} {r.is_demo ? <Badge tone="warn">Demo</Badge> : null}
                  {r.analysis_status === "verified" || r.analysis_status === "rounded" ? <Badge tone="ok">Data sheet</Badge> : null}
                  {r.analysis_status === "unverified" ? <Badge tone="warn">Printed rate only</Badge> : null}
                </td>
                <td className="px-2 py-1.5 text-right">
                  {r.can_edit ? (
                    <span className="flex justify-end gap-2 text-xs">
                      <button className="text-accent hover:underline" onClick={() => setEditing(r)}>
                        Edit
                      </button>
                      <button
                        className="text-bad hover:underline"
                        onClick={async () => {
                          if (!window.confirm(`Delete ${r.item_code}?`)) return;
                          try {
                            await del(`/rate-items/${r.id}`);
                            await refresh();
                          } catch (e) {
                            setError(e instanceof ApiError ? e.message : "Could not delete.");
                          }
                        }}
                      >
                        Delete
                      </button>
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {result && !result.items.length ? <p className="p-3 text-muted">No rates match.</p> : null}
      </div>
      {result && result.total > PAGE ? (
        <div className="flex items-center gap-3 text-sm">
          <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </Button>
          <span className="text-muted">
            {offset + 1}–{Math.min(offset + PAGE, result.total)} of {result.total}
          </span>
          <Button variant="secondary" disabled={offset + PAGE >= result.total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </Button>
        </div>
      ) : null}
      {!admin ? <p className="text-xs text-muted">Only workspace owners and admins can add or change rates.</p> : null}

      {addingSource ? (
        <SourceDialog
          onClose={() => setAddingSource(false)}
          onSaved={async (s) => {
            setAddingSource(false);
            await loadSources();
            setSourceId(s.id);
          }}
        />
      ) : null}
      {editing ? (
        <ItemDialog
          units={units}
          item={editing === "new" ? null : editing}
          sourceId={editing === "new" ? sourceId : editing.source_id}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function useSubmit() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, submit };
}

function SourceDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (s: RateSource) => Promise<void> }) {
  const [form, setForm] = useState({
    sor_name: "",
    year: "2026-27",
    state: "Telangana",
    department: "",
    effective_from: "2026-04-01",
    effective_to: "",
    source_reference: "",
  });
  const { error, busy, submit } = useSubmit();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));
  return (
    <Modal title="Add a rate source" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(async () => {
            const s = await post<RateSource>("/rate-sources", {
              ...form,
              effective_to: form.effective_to || null,
              source_reference: form.source_reference || null,
            });
            await onSaved(s);
          });
        }}
      >
        {error ? <Alert>{error}</Alert> : null}
        <Field label="Name" required hint="e.g. R&B SSR">
          <Input value={form.sor_name} onChange={set("sor_name")} required maxLength={200} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Year" required hint="e.g. 2026-27">
            <Input value={form.year} onChange={set("year")} required pattern="\d{4}-\d{2}" />
          </Field>
          <Field label="Department" required>
            <Input value={form.department} onChange={set("department")} required maxLength={120} />
          </Field>
          <Field label="State" required>
            <Input value={form.state} onChange={set("state")} required maxLength={80} />
          </Field>
          <Field label="Reference" hint="G.O. or document number">
            <Input value={form.source_reference} onChange={set("source_reference")} maxLength={300} />
          </Field>
          <Field label="Effective from" required>
            <Input type="date" value={form.effective_from} onChange={set("effective_from")} required />
          </Field>
          <Field label="Effective to">
            <Input type="date" value={form.effective_to} onChange={set("effective_to")} />
          </Field>
        </div>
        <p className="text-xs text-muted">Rates you enter are marked “entered by you”, not verified official rates.</p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            Add source
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ItemDialog({
  item,
  sourceId,
  units,
  onClose,
  onSaved,
}: {
  item: RateItem | null;
  sourceId: string;
  units: Unit[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<ItemForm>(
    item
      ? { item_code: item.item_code, description: item.description, unit: item.unit, rate: item.rate }
      : { item_code: "", description: "", unit: "cum", rate: "" },
  );
  const { error, busy, submit } = useSubmit();
  const set = (key: keyof ItemForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  return (
    <Modal title={item ? `Edit ${item.item_code}` : "Add a rate"} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(async () => {
            if (item) await patch(`/rate-items/${item.id}`, form);
            else await post(`/rate-sources/${sourceId}/items`, form);
            await onSaved();
          });
        }}
      >
        {error ? <Alert>{error}</Alert> : null}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Item code" required>
            <Input value={form.item_code} onChange={set("item_code")} required maxLength={50} />
          </Field>
          <Field label="Unit" required>
            <Select value={form.unit} onChange={set("unit")}>
              {units.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.display_name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Rate ₹" required>
            <Input inputMode="decimal" value={form.rate} onChange={set("rate")} required className="num text-right" />
          </Field>
        </div>
        <Field label="Description" required>
          <Input value={form.description} onChange={set("description")} required maxLength={5000} />
        </Field>
        {item ? (
          <Card>
            <p className="text-xs text-muted">Estimates that already use this rate keep the rate they picked.</p>
          </Card>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
