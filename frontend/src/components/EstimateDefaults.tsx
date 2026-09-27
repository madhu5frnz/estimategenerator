"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError, put, type EstimateDefaults } from "@/lib/api";

type ChargeRow = { name: string; kind: string; percentage: string; base: string };

/** GST, charges and rounding that new estimates start with (nothing unless set here). */
export function EstimateDefaultsCard({ orgId }: { orgId: string }) {
  const path = `/organizations/${orgId}/settings/estimate-defaults`;
  const [loaded, setLoaded] = useState<EstimateDefaults | null>(null);
  const [gstOn, setGstOn] = useState(false);
  const [rate, setRate] = useState("");
  const [supply, setSupply] = useState("intra");
  const [rounding, setRounding] = useState("nearest_rupee");
  const [charges, setCharges] = useState<ChargeRow[]>([]);
  const [saved, setSaved] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  useEffect(() => {
    api<EstimateDefaults>(path)
      .then((d) => {
        setLoaded(d);
        setGstOn(d.gst.applicable);
        setRate(d.gst.rate_pct ?? "");
        setSupply(d.gst.supply);
        setRounding(d.rounding);
        setCharges(d.charges.map((c) => ({ name: c.name, kind: c.kind, percentage: c.percentage ?? "", base: c.base })));
      })
      .catch(() => setSaved({ tone: "bad", text: "Could not load the defaults." }));
  }, [path]);

  if (!loaded) return null;
  const edit = loaded.can_edit;

  async function save() {
    setSaved(null);
    try {
      await put(path, {
        gst: { applicable: gstOn, supply, mode: "exclusive", base: "after_charges", rate_pct: rate || null },
        charges: charges.filter((c) => c.name.trim()).map((c) => ({ name: c.name, kind: c.kind, percentage: c.percentage, base: c.base })),
        rounding,
      });
      setSaved({ tone: "ok", text: "Saved. New estimates start with these settings." });
    } catch (e) {
      setSaved({ tone: "bad", text: e instanceof ApiError ? e.message : "Could not save." });
    }
  }

  return (
    <Card title="Estimate defaults" actions={edit ? null : <Badge>Only owners and admins can edit</Badge>}>
      <div className="space-y-4">
        <p className="text-xs text-muted">
          Applied to new estimates only. Each estimate can change them in its Abstract tab. There is no built-in GST rate or
          charge percentage: enter the ones your work uses.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="flex items-center gap-2 sm:col-span-3">
            <input type="checkbox" disabled={!edit} checked={gstOn} onChange={(e) => setGstOn(e.target.checked)} />
            Add GST to new estimates
          </label>
          {gstOn ? (
            <>
              <Field label="GST rate %" required>
                <Input disabled={!edit} inputMode="decimal" placeholder="e.g. 18" value={rate} onChange={(e) => setRate(e.target.value)} />
              </Field>
              <Field label="Supply">
                <Select disabled={!edit} value={supply} onChange={(e) => setSupply(e.target.value)}>
                  <option value="intra">CGST + SGST</option>
                  <option value="inter">IGST</option>
                </Select>
              </Field>
            </>
          ) : null}
          <Field label="Round grand total">
            <Select disabled={!edit} value={rounding} onChange={(e) => setRounding(e.target.value)}>
              <option value="none">No rounding</option>
              <option value="nearest_rupee">Nearest ₹1</option>
              <option value="nearest_10">Nearest ₹10</option>
              <option value="nearest_100">Nearest ₹100</option>
              <option value="nearest_1000">Nearest ₹1,000</option>
            </Select>
          </Field>
        </div>
        <div className="space-y-2">
          <div className="text-sm font-medium">Charges</div>
          {charges.map((c, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input
                aria-label="Charge name"
                disabled={!edit}
                value={c.name}
                onChange={(e) => setCharges((cs) => cs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                className="w-56"
              />
              <Input
                aria-label="Charge percentage"
                disabled={!edit}
                inputMode="decimal"
                value={c.percentage}
                onChange={(e) => setCharges((cs) => cs.map((x, j) => (j === i ? { ...x, percentage: e.target.value } : x)))}
                className="num w-24 text-right"
              />
              <span className="text-muted">% of</span>
              <Select
                aria-label="Charge base"
                disabled={!edit}
                value={c.base}
                onChange={(e) => setCharges((cs) => cs.map((x, j) => (j === i ? { ...x, base: e.target.value } : x)))}
                className="w-48"
              >
                <option value="works_subtotal">works subtotal</option>
                <option value="running_total">running total</option>
              </Select>
              {edit ? (
                <button className="text-xs text-bad hover:underline" onClick={() => setCharges((cs) => cs.filter((_, j) => j !== i))}>
                  Remove
                </button>
              ) : null}
            </div>
          ))}
          {edit ? (
            <Button
              variant="secondary"
              className="py-1"
              onClick={() =>
                setCharges((cs) => [...cs, { name: cs.length ? "" : "Contingencies", kind: cs.length ? "other" : "contingency", percentage: "", base: "works_subtotal" }])
              }
            >
              Add charge
            </Button>
          ) : null}
        </div>
        {edit ? (
          <div className="flex items-end gap-3">
            <Button onClick={() => void save()} disabled={gstOn && !rate}>
              Save defaults
            </Button>
            {saved ? <Alert tone={saved.tone}>{saved.text}</Alert> : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
