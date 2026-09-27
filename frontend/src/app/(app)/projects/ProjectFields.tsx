"use client";

import { useEffect, useState } from "react";

import { Field, Input, Select, Textarea } from "@/components/ui";
import { api, type Option, type WorkCategory } from "@/lib/api";
import { INDIAN_STATES } from "@/lib/india";

export type ProjectFormValues = {
  name: string;
  project_type: string;
  work_category_id: string;
  estimated_value: string;
  description: string;
  location: string;
  district: string;
  state: string;
  client_department: string;
  engineer_name: string;
  contractor_name: string;
  reference_number: string;
  project_date: string;
};

export const EMPTY_PROJECT: ProjectFormValues = {
  name: "", project_type: "", work_category_id: "", estimated_value: "", description: "",
  location: "", district: "", state: "Telangana", client_department: "", engineer_name: "",
  contractor_name: "", reference_number: "", project_date: "",
};

export const STEP_FIELDS: (keyof ProjectFormValues)[][] = [
  ["name", "project_type", "work_category_id", "estimated_value", "description"],
  ["location", "district", "state", "client_department", "engineer_name", "contractor_name", "reference_number", "project_date"],
];

/** Form values → API body. Empty strings become null; the backend validates everything. */
export function toPayload(values: ProjectFormValues): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(values)) {
    const trimmed = value.trim();
    out[key] = trimmed === "" ? null : trimmed;
  }
  if (out.estimated_value) out.estimated_value = out.estimated_value.replace(/,/g, "");
  return out;
}

export function checkStep(values: ProjectFormValues, step: number): Record<string, string> {
  const errors: Record<string, string> = {};
  if (step === 0) {
    if (!values.name.trim()) errors.name = "Project name is required.";
    if (!values.project_type) errors.project_type = "Choose a project type.";
    const value = values.estimated_value.replace(/,/g, "").trim();
    if (value && !/^\d+(\.\d{1,2})?$/.test(value)) errors.estimated_value = "Enter an amount in rupees, e.g. 3097500 or 3097500.50.";
  }
  if (step === 1 && !values.state.trim()) errors.state = "State is required.";
  return errors;
}

type Props = {
  values: ProjectFormValues;
  errors: Record<string, string>;
  onChange: (changes: Partial<ProjectFormValues>) => void;
  step?: number; // undefined = show every field
};

export function ProjectFields({ values, errors, onChange, step }: Props) {
  const [types, setTypes] = useState<Option[]>([]);
  // Categories are remembered with the type they belong to, so a stale list is never shown.
  const [loaded, setLoaded] = useState<{ type: string; list: WorkCategory[] }>({ type: "", list: [] });

  useEffect(() => {
    api<Option[]>("/project-types").then(setTypes).catch(() => setTypes([]));
  }, []);
  useEffect(() => {
    const type = values.project_type;
    if (!type) return;
    api<WorkCategory[]>(`/work-categories?project_type=${type}`)
      .then((list) => setLoaded({ type, list }))
      .catch(() => setLoaded({ type, list: [] }));
  }, [values.project_type]);
  const categories = loaded.type === values.project_type ? loaded.list : [];

  const show = (s: number) => step === undefined || step === s;
  const text = (key: keyof ProjectFormValues) => ({
    value: values[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange({ [key]: e.target.value }),
    "aria-invalid": Boolean(errors[key]),
  });

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {show(0) ? (
        <>
          <Field label="Project name" error={errors.name} required className="md:col-span-2">
            <Input {...text("name")} maxLength={200} placeholder="e.g. CC Road Miryalaguda" />
          </Field>
          <Field label="Project type" error={errors.project_type} required>
            <Select
              value={values.project_type}
              aria-invalid={Boolean(errors.project_type)}
              onChange={(e) => onChange({ project_type: e.target.value, work_category_id: "" })}
            >
              <option value="">Choose…</option>
              {types.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Work category" error={errors.work_category_id}>
            <Select
              value={values.work_category_id}
              disabled={!values.project_type}
              onChange={(e) => onChange({ work_category_id: e.target.value })}
            >
              <option value="">{values.project_type ? "None" : "Choose a type first"}</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Estimated project value (₹)" error={errors.estimated_value} hint="Optional. Your own budget figure.">
            <Input {...text("estimated_value")} inputMode="decimal" className="num" placeholder="e.g. 3097500" />
          </Field>
          <Field label="Description" error={errors.description} className="md:col-span-2">
            <Textarea {...text("description")} rows={3} maxLength={5000} />
          </Field>
        </>
      ) : null}
      {show(1) ? (
        <>
          <Field label="Location / village" error={errors.location}>
            <Input {...text("location")} maxLength={200} />
          </Field>
          <Field label="District" error={errors.district}>
            <Input {...text("district")} maxLength={100} />
          </Field>
          <Field label="State" error={errors.state} required>
            <Select value={values.state} onChange={(e) => onChange({ state: e.target.value })}>
              {INDIAN_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Department / client" error={errors.client_department}>
            <Input {...text("client_department")} maxLength={200} placeholder="e.g. R&B, I&CAD, Panchayat Raj" />
          </Field>
          <Field label="Engineer / consultant" error={errors.engineer_name}>
            <Input {...text("engineer_name")} maxLength={120} />
          </Field>
          <Field label="Contractor" error={errors.contractor_name}>
            <Input {...text("contractor_name")} maxLength={120} />
          </Field>
          <Field label="Reference number" error={errors.reference_number}>
            <Input {...text("reference_number")} maxLength={100} />
          </Field>
          <Field label="Date" error={errors.project_date}>
            <Input type="date" {...text("project_date")} />
          </Field>
        </>
      ) : null}
    </div>
  );
}
