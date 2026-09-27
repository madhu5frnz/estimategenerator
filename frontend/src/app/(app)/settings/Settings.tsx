"use client";

import { useState } from "react";

import { useSession } from "@/components/Session";
import { Alert, Badge, Button, Card, Field, Input, Select, Textarea } from "@/components/ui";
import { ApiError, patch } from "@/lib/api";
import { indianDate } from "@/lib/format";

// Two-letter GST state codes used by the org's GST defaults (CGST+SGST vs IGST) from M5.
const STATE_CODES: [string, string][] = [
  ["TS", "Telangana"], ["AP", "Andhra Pradesh"], ["KA", "Karnataka"], ["MH", "Maharashtra"],
  ["TN", "Tamil Nadu"], ["KL", "Kerala"], ["GJ", "Gujarat"], ["DL", "Delhi"], ["OD", "Odisha"],
  ["WB", "West Bengal"], ["UP", "Uttar Pradesh"], ["MP", "Madhya Pradesh"], ["RJ", "Rajasthan"],
  ["CG", "Chhattisgarh"], ["BR", "Bihar"], ["PB", "Punjab"], ["HR", "Haryana"], ["GA", "Goa"],
];

type Saved = { tone: "ok" | "bad"; text: string } | null;

function useForm<T extends Record<string, string>>(initial: T) {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Saved>(null);
  const [busy, setBusy] = useState(false);
  const bind = (key: keyof T & string) => ({
    value: values[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setValues((v) => ({ ...v, [key]: e.target.value })),
    "aria-invalid": Boolean(errors[key]),
  });
  async function submit(path: string, after: () => Promise<void>) {
    setBusy(true);
    setSaved(null);
    setErrors({});
    try {
      await patch(path, values);
      await after();
      setSaved({ tone: "ok", text: "Saved." });
    } catch (e) {
      if (e instanceof ApiError) {
        const fields = e.fieldErrors();
        setErrors(fields);
        setSaved({ tone: "bad", text: Object.keys(fields).length ? "Please correct the highlighted fields." : e.message });
      } else setSaved({ tone: "bad", text: "Could not save." });
    } finally {
      setBusy(false);
    }
  }
  return { values, errors, saved, busy, bind, submit };
}

export function Settings() {
  const { me, reload } = useSession();
  const orgAdmin = ["owner", "admin"].includes(me.organization.role);
  const profile = useForm({ full_name: me.user.full_name, phone: me.user.phone ?? "" });
  const org = useForm({
    name: me.organization.name,
    gstin: me.organization.gstin ?? "",
    state_code: me.organization.state_code ?? "",
    address: me.organization.address ?? "",
  });
  const limits = me.subscription.limits as Record<string, number | null>;
  const features = me.subscription.features as Record<string, boolean>;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <Card title="Your profile">
        <form
          className="grid gap-4 sm:grid-cols-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void profile.submit("/me", reload);
          }}
        >
          <Field label="Full name" error={profile.errors.full_name}>
            <Input {...profile.bind("full_name")} maxLength={120} />
          </Field>
          <Field label="Mobile number" error={profile.errors.phone} hint="Optional, e.g. +91 98765 43210">
            <Input {...profile.bind("phone")} inputMode="tel" maxLength={20} />
          </Field>
          <Field label="Email" hint={me.user.email_verified ? "Confirmed" : "Not yet confirmed"}>
            <Input value={me.user.email} disabled readOnly />
          </Field>
          <div className="flex items-end gap-3 sm:col-span-2">
            <Button type="submit" disabled={profile.busy}>
              Save profile
            </Button>
            {profile.saved ? <Alert tone={profile.saved.tone}>{profile.saved.text}</Alert> : null}
          </div>
        </form>
      </Card>

      <Card title="Workspace" actions={orgAdmin ? null : <Badge>Only owners and admins can edit</Badge>}>
        <form
          className="grid gap-4 sm:grid-cols-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void org.submit(`/organizations/${me.organization.id}`, reload);
          }}
        >
          <Field label="Company / department name" error={org.errors.name} className="sm:col-span-2">
            <Input {...org.bind("name")} disabled={!orgAdmin} maxLength={160} />
          </Field>
          <Field label="GSTIN" error={org.errors.gstin} hint="Optional, 15 characters">
            <Input {...org.bind("gstin")} disabled={!orgAdmin} maxLength={15} className="uppercase" />
          </Field>
          <Field label="State (for GST)" error={org.errors.state_code}>
            <Select {...org.bind("state_code")} disabled={!orgAdmin}>
              <option value="">Not set</option>
              {STATE_CODES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Address (used on exported documents)" error={org.errors.address} className="sm:col-span-2">
            <Textarea {...org.bind("address")} disabled={!orgAdmin} rows={3} maxLength={500} />
          </Field>
          {orgAdmin ? (
            <div className="flex items-end gap-3 sm:col-span-2">
              <Button type="submit" disabled={org.busy}>
                Save workspace
              </Button>
              {org.saved ? <Alert tone={org.saved.tone}>{org.saved.text}</Alert> : null}
            </div>
          ) : null}
        </form>
      </Card>

      <Card title="Plan">
        <dl className="grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted">Current plan</dt>
            <dd className="font-medium">{me.subscription.plan_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Projects</dt>
            <dd className="num">
              {me.usage.projects} of {limits.projects ?? "unlimited"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Renews</dt>
            <dd>{indianDate(me.subscription.current_period_end)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">AI generations per month</dt>
            <dd className="num">{limits.ai_generations_per_period ?? "unlimited"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Exports</dt>
            <dd>
              {[features.export_pdf && "PDF", features.export_xlsx && "Excel", features.export_docx && "Word"]
                .filter(Boolean)
                .join(", ") || "—"}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-muted">Upgrading with UPI, cards or net banking arrives with billing in M7.</p>
      </Card>
    </div>
  );
}
