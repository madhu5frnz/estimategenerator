"use client";

import { useEffect, useState } from "react";

import { Modal } from "@/components/Modal";
import { Alert, Badge, Button, Input } from "@/components/ui";
import { api, ApiError, post, type Item, type RateItem, type RateSearch, type Version } from "@/lib/api";
import { inr } from "@/lib/format";

type Pending = { rate: RateItem; message: string };

/**
 * Search the rate list and take a rate for one BOQ item. Only rates in the item's unit are
 * listed (an item without a unit takes the rate's unit). Replacing a rate typed by hand
 * asks first; the server enforces both rules.
 */
export function RatePicker({
  item,
  onPicked,
  onClose,
}: {
  item: Item;
  onPicked: (version: Version) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState(item.description.split(/\s+/).slice(0, 3).join(" "));
  const [anyUnit, setAnyUnit] = useState(false);
  const [result, setResult] = useState<RateSearch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams({ limit: "30" });
    if (q.trim()) params.set("q", q.trim());
    if (item.unit && !anyUnit) params.set("unit", item.unit);
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
  }, [q, anyUnit, item.unit]);

  async function pick(rate: RateItem, confirm = false) {
    setBusy(true);
    setError(null);
    try {
      const version = await post<Version>(`/boq-items/${item.id}/set-rate`, {
        rate_item_id: rate.id,
        confirm_overwrite: confirm,
      });
      onPicked(version);
    } catch (e) {
      if (e instanceof ApiError && e.errorCode === "RATE_OVERWRITE_REQUIRES_CONFIRMATION") {
        setPending({ rate, message: e.message });
      } else {
        setError(e instanceof ApiError ? e.message : "Could not set the rate.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Pick a rate for item ${item.item_no_display}`} onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-muted">
          {item.description}
          {item.unit_display ? ` · per ${item.unit_display}` : " · no unit yet (the rate's unit will be used)"}
        </p>
        {error ? <Alert>{error}</Alert> : null}
        {pending ? (
          <Alert tone="warn">
            <p>{pending.message}</p>
            <div className="mt-2 flex gap-2">
              <Button disabled={busy} onClick={() => void pick(pending.rate, true)}>
                Replace rate
              </Button>
              <Button variant="secondary" onClick={() => setPending(null)}>
                Keep my rate
              </Button>
            </div>
          </Alert>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Input
            aria-label="Search rates"
            placeholder="Search by description or item code"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="min-w-64 flex-1"
            autoFocus
          />
          {item.unit ? (
            <label className="flex items-center gap-1 text-xs text-muted">
              <input type="checkbox" checked={anyUnit} onChange={(e) => setAnyUnit(e.target.checked)} />
              Show other units
            </label>
          ) : null}
        </div>
        <div className="overflow-x-auto rounded border border-line">
          <table className="w-full min-w-[640px] text-left">
            <thead className="bg-panel text-xs text-muted uppercase">
              <tr>
                <th className="px-2 py-2">Code</th>
                <th className="px-2 py-2">Description</th>
                <th className="px-2 py-2">Unit</th>
                <th className="px-2 py-2 text-right">Rate</th>
                <th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {result?.items.map((r) => {
                const mismatch = Boolean(item.unit && item.unit !== r.unit);
                return (
                  <tr key={r.id} className="border-t border-line align-top">
                    <td className="px-2 py-1.5 font-mono text-xs">{r.item_code}</td>
                    <td className="px-2 py-1.5">
                      {r.description}
                      <div className="mt-0.5 flex flex-wrap gap-1 text-xs text-muted">
                        {r.source_label}
                        {r.is_demo ? <Badge tone="warn">Demo · not official SOR</Badge> : null}
                        {r.is_expired ? <Badge tone="warn">Expired</Badge> : null}
                      </div>
                    </td>
                    <td className="px-2 py-1.5">{r.unit_display}</td>
                    <td className="num px-2 py-1.5 text-right">{r.rate_display}</td>
                    <td className="px-2 py-1.5 text-right">
                      <Button
                        variant="secondary"
                        className="py-1"
                        disabled={busy || mismatch}
                        title={mismatch ? `The item is per ${item.unit_display}` : undefined}
                        onClick={() => void pick(r)}
                      >
                        Use
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {result && result.items.length === 0 ? (
            <p className="p-3 text-muted">
              No rates found{item.unit && !anyUnit ? ` in ${item.unit_display}` : ""}. Add rates on the Rate Database page.
            </p>
          ) : null}
          {!result ? <p className="p-3 text-muted">Searching…</p> : null}
        </div>
        {result && result.total > result.items.length ? (
          <p className="text-xs text-muted">
            Showing {result.items.length} of {result.total}. Narrow the search to see others.
          </p>
        ) : null}
        <p className="text-xs text-muted">
          Current rate: {item.rate ? inr(item.rate) : "none"}. The estimate keeps a copy of the rate you pick; later changes to
          the rate list do not change it.
        </p>
      </div>
    </Modal>
  );
}
