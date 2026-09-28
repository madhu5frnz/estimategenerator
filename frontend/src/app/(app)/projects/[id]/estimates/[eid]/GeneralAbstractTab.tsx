"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import { api, ApiError, patch, type GeneralAbstract, type MethodSettings } from "@/lib/api";
import { inr } from "@/lib/format";

import type { WorkspaceProps } from "./context";

type LumpSum = { label: string; amount: string; stage: "before_gst" | "after_gst" };
type AbstractConfig = {
  item_rounding: string;
  labour_cess_pct: string;
  nac_pct: string;
  cess_rounding: string;
  nac_rounding: string;
  gst_pct: string;
  gst_rounding: string;
  final: string;
  unforeseen: string;
  lump_sums: LumpSum[];
};
type SeigConfig = { rates: Record<string, string>; dmf_pct: string; smet_pct: string; permit_fee_pct: string; permit_fee_materials: string[]; sand_split: string };

const ROUNDING: [string, string][] = [
  ["none", "Exact"],
  ["paise", "To paise"],
  ["rupee", "To rupee"],
];

/** General Abstract in the Telangana I&CAD order. */
export function GeneralAbstractTab({ version, onOpenData }: WorkspaceProps & { onOpenData: (itemId: string) => void }) {
  const vid = version.version.id;
  const [data, setData] = useState<GeneralAbstract | null>(null);
  const [settings, setSettings] = useState<MethodSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<GeneralAbstract>(`/versions/${vid}/general-abstract`), api<MethodSettings>(`/versions/${vid}/method-settings`)])
      .then(([a, s]) => {
        if (cancelled) return;
        setData(a);
        setSettings(s);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the abstract."));
    return () => {
      cancelled = true;
    };
  }, [vid, version]);

  async function saveSettings(body: Record<string, unknown>): Promise<boolean> {
    setError(null);
    try {
      setSettings(await patch<MethodSettings>(`/versions/${vid}/method-settings`, body));
      setData(await api<GeneralAbstract>(`/versions/${vid}/general-abstract`));
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the settings.");
      return false;
    }
  }

  if (!data || !settings) return error ? <Alert>{error}</Alert> : <p className="text-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      {error ? <Alert>{error}</Alert> : null}
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-panel text-xs text-muted uppercase">
            <tr>
              <th className="w-12 px-2 py-2 text-left">S.No</th>
              <th className="w-36 px-2 py-2 text-left">Item code</th>
              <th className="px-2 py-2 text-left">Description of item</th>
              <th className="w-24 px-2 py-2 text-right">Qty</th>
              <th className="w-24 px-2 py-2 text-right">Unit rate</th>
              <th className="w-16 px-2 py-2 text-left">Unit</th>
              <th className="w-32 px-2 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.item_id} className="border-t border-line align-top">
                <td className="px-2 py-1.5">{i.sl_no}</td>
                <td className="px-2 py-1.5 text-xs">{i.code}</td>
                <td className="px-2 py-1.5">
                  {i.description}
                  {i.has_analysis ? (
                    <button className="ml-2 text-xs text-accent hover:underline" onClick={() => onOpenData(i.item_id)}>
                      data
                    </button>
                  ) : null}
                </td>
                <td className="num px-2 py-1.5 text-right">{i.quantity}</td>
                <td className="num px-2 py-1.5 text-right">{i.rate}</td>
                <td className="px-2 py-1.5">{i.unit}</td>
                <td className="num px-2 py-1.5 text-right">{inr(i.amount).slice(1)}</td>
              </tr>
            ))}
          </tbody>
          <tbody className="border-t-2 border-line">
            <Total label="Part A — Estimated cost of works (E.C.V.)" value={data.ecv} strong />
            {data.part_b.map((l) => (
              <Total key={l.label} label={l.label} value={l.amount} />
            ))}
            <Total label="Sub total (Part A + Part B)" value={data.subtotal} strong />
            <Total label={`Provision towards GST @ ${data.gst_pct} %`} value={data.gst} />
            {data.after_gst.map((l) => (
              <Total key={l.label} label={l.label} value={l.amount} />
            ))}
            {data.rounding_off !== "0.00" ? <Total label="Rounding off and unforeseen expenditure" value={data.rounding_off} /> : null}
            <Total label="TOTAL" value={data.total} strong />
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">
            {inr(data.total)} <Badge tone="accent">Rs {data.total_in_lakhs} Lakhs</Badge>
          </div>
          <p className="text-sm">{data.amount_in_words}</p>
        </div>
        <Button variant="secondary" onClick={() => setShowSettings((v) => !v)}>
          {showSettings ? "Hide settings" : "Settings"}
        </Button>
      </div>
      {showSettings ? <SettingsPanel settings={settings} onSave={saveSettings} /> : null}
    </div>
  );
}

function Total({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <tr className={`border-t border-line ${strong ? "bg-panel/60 font-semibold" : ""}`}>
      <td />
      <td colSpan={5} className="px-2 py-1.5">
        {label}
      </td>
      <td className="num px-2 py-1.5 text-right">{inr(value).slice(1)}</td>
    </tr>
  );
}

function SettingsPanel({ settings, onSave }: { settings: MethodSettings; onSave: (body: Record<string, unknown>) => Promise<boolean> }) {
  const cfg = settings.config as { zone: string; abstract: AbstractConfig; seigniorage: SeigConfig };
  const [ab, setAb] = useState<AbstractConfig>(cfg.abstract);
  const [sg, setSg] = useState<SeigConfig>(cfg.seigniorage);
  const [zone, setZone] = useState(cfg.zone);
  const edit = settings.can_edit;
  const set = (k: keyof AbstractConfig) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setAb({ ...ab, [k]: e.target.value });

  return (
    <Card title="Estimate settings">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Zone (labour, hire, lead)">
          <Select disabled={!edit} value={zone} onChange={(e) => setZone(e.target.value)}>
            <option value="I">Zone I — Municipal Corporations</option>
            <option value="II">Zone II — Municipalities</option>
            <option value="III">Zone III — Rural and other areas</option>
          </Select>
        </Field>
        <Field label="Item amounts (qty × rate)">
          <Select disabled={!edit} value={ab.item_rounding} onChange={set("item_rounding")}>
            {ROUNDING.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
        </Field>
        <Field label="GST %">
          <Input disabled={!edit} value={ab.gst_pct} onChange={set("gst_pct")} />
        </Field>
        <Field label="Labour cess %">
          <Input disabled={!edit} value={ab.labour_cess_pct} onChange={set("labour_cess_pct")} />
        </Field>
        <Field label="NAC %">
          <Input disabled={!edit} value={ab.nac_pct} onChange={set("nac_pct")} />
        </Field>
        <Field label="Cess / NAC / GST rounding">
          <Select disabled={!edit} value={ab.cess_rounding}
            onChange={(e) => setAb({ ...ab, cess_rounding: e.target.value, nac_rounding: e.target.value, gst_rounding: e.target.value })}>
            {ROUNDING.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
        </Field>
        <Field label="Final total">
          <Select disabled={!edit} value={ab.final} onChange={set("final")}>
            <option value="none">As calculated</option>
            <option value="round_up_1000_plus_unforeseen">Round up to Rs 1,000 + unforeseen</option>
          </Select>
        </Field>
        {ab.final !== "none" ? (
          <Field label="Unforeseen expenditure Rs">
            <Input disabled={!edit} value={ab.unforeseen} onChange={set("unforeseen")} />
          </Field>
        ) : null}
      </div>

      <div className="mt-4 space-y-2">
        <div className="text-sm font-medium">Lump-sum provisions</div>
        {ab.lump_sums.map((l, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Input aria-label="Provision" disabled={!edit} value={l.label} className="w-80"
              onChange={(e) => setAb({ ...ab, lump_sums: ab.lump_sums.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
            <Input aria-label="Amount" disabled={!edit} value={l.amount} className="num w-32 text-right"
              onChange={(e) => setAb({ ...ab, lump_sums: ab.lump_sums.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)) })} />
            <Select aria-label="Stage" disabled={!edit} value={l.stage} className="w-44"
              onChange={(e) => setAb({ ...ab, lump_sums: ab.lump_sums.map((x, j) => (j === i ? { ...x, stage: e.target.value as LumpSum["stage"] } : x)) })}>
              <option value="before_gst">Part B (before GST)</option>
              <option value="after_gst">After GST</option>
            </Select>
            {edit ? (
              <button className="text-xs text-bad hover:underline" onClick={() => setAb({ ...ab, lump_sums: ab.lump_sums.filter((_, j) => j !== i) })}>
                remove
              </button>
            ) : null}
          </div>
        ))}
        {edit ? (
          <Button variant="secondary" className="py-1"
            onClick={() => setAb({ ...ab, lump_sums: [...ab.lump_sums, { label: "Provision for advertisement, stationery and photographs", amount: "0", stage: "after_gst" }] })}>
            Add provision
          </Button>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="text-sm font-medium sm:col-span-3">Seigniorage ({settings.seigniorage_note})</div>
        {Object.entries(sg.rates).map(([k, v]) => (
          <Field key={k} label={`${settings.seigniorage_materials[k] ?? k} rate`}>
            <Input disabled={!edit} value={v} onChange={(e) => setSg({ ...sg, rates: { ...sg.rates, [k]: e.target.value } })} />
          </Field>
        ))}
        <Field label="DMF %">
          <Input disabled={!edit} value={sg.dmf_pct} onChange={(e) => setSg({ ...sg, dmf_pct: e.target.value })} />
        </Field>
        <Field label="SMET %">
          <Input disabled={!edit} value={sg.smet_pct} onChange={(e) => setSg({ ...sg, smet_pct: e.target.value })} />
        </Field>
        <Field label="Permit fee %">
          <Input disabled={!edit} value={sg.permit_fee_pct} onChange={(e) => setSg({ ...sg, permit_fee_pct: e.target.value })} />
        </Field>
        <fieldset className="sm:col-span-3">
          <legend className="mb-1 text-xs text-muted">Permit fee on</legend>
          <div className="flex flex-wrap gap-3">
            {Object.keys(sg.rates).map((k) => (
              <label key={k} className="flex items-center gap-1 text-sm">
                <input type="checkbox" disabled={!edit} checked={sg.permit_fee_materials.includes(k)}
                  onChange={(e) => setSg({ ...sg, permit_fee_materials: e.target.checked ? [...sg.permit_fee_materials, k] : sg.permit_fee_materials.filter((m) => m !== k) })} />
                {settings.seigniorage_materials[k] ?? k}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Sand in concrete">
          <Select disabled={!edit} value={sg.sand_split} onChange={(e) => setSg({ ...sg, sand_split: e.target.value })}>
            <option value="natural">All natural sand</option>
            <option value="50_50">50 % river sand, 50 % M-sand (GO Ms 37)</option>
          </Select>
        </Field>
      </div>
      {edit ? (
        <Button className="mt-4" onClick={() => void onSave({ zone, abstract: ab, seigniorage: sg })}>
          Save settings
        </Button>
      ) : null}
    </Card>
  );
}
