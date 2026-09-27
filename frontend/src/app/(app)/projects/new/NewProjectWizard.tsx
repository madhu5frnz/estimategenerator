"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { ApiError, post, type Project } from "@/lib/api";
import { inr } from "@/lib/format";

import { checkStep, EMPTY_PROJECT, ProjectFields, type ProjectFormValues, STEP_FIELDS, toPayload } from "../ProjectFields";

const STEPS = ["Basics", "Location & parties", "Review"];
const LABELS: Record<keyof ProjectFormValues, string> = {
  name: "Project name", project_type: "Project type", work_category_id: "Work category",
  estimated_value: "Estimated value", description: "Description", location: "Location",
  district: "District", state: "State", client_department: "Department / client",
  engineer_name: "Engineer / consultant", contractor_name: "Contractor",
  reference_number: "Reference number", project_date: "Date",
};

export function NewProjectWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<ProjectFormValues>(EMPTY_PROJECT);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<{ message: string; limit?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const onChange = (changes: Partial<ProjectFormValues>) => setValues((v) => ({ ...v, ...changes }));

  function next() {
    const found = checkStep(values, step);
    setErrors(found);
    if (!Object.keys(found).length) setStep((s) => s + 1);
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const project = await post<Project>("/projects", toPayload(values));
      router.push(`/projects/${project.id}`);
    } catch (e) {
      setBusy(false);
      if (!(e instanceof ApiError)) return setError({ message: "Could not create the project." });
      const fields = e.fieldErrors();
      if (Object.keys(fields).length) {
        setErrors(fields);
        const firstStep = STEP_FIELDS.findIndex((group) => group.some((f) => f in fields));
        if (firstStep >= 0) setStep(firstStep);
        return;
      }
      setError({ message: e.message, limit: e.errorCode === "PLAN_LIMIT_REACHED" });
    }
  }

  return (
    <div className="max-w-3xl space-y-5">
      <h1 className="text-xl font-semibold">New project</h1>
      <ol className="flex flex-wrap gap-2 text-xs">
        {STEPS.map((label, i) => (
          <li
            key={label}
            aria-current={i === step ? "step" : undefined}
            className={`rounded px-3 py-1 ${i === step ? "bg-accent text-white" : i < step ? "bg-accent-soft text-accent" : "bg-panel text-muted"}`}
          >
            {i + 1}. {label}
          </li>
        ))}
      </ol>

      {error ? (
        <Alert>
          {error.message}{" "}
          {error.limit ? (
            <Link href="/projects" className="underline">
              Go to projects
            </Link>
          ) : null}
        </Alert>
      ) : null}

      <Card>
        {step < 2 ? (
          <ProjectFields values={values} errors={errors} onChange={onChange} step={step} />
        ) : (
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {(Object.keys(LABELS) as (keyof ProjectFormValues)[])
              .filter((k) => k !== "work_category_id")
              .map((key) => (
                <div key={key} className={key === "description" ? "sm:col-span-2" : ""}>
                  <dt className="text-xs text-muted">{LABELS[key]}</dt>
                  <dd className="whitespace-pre-wrap">
                    {key === "estimated_value" ? inr(values[key].replace(/,/g, "") || null) : values[key] || "—"}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </Card>

      <div className="flex justify-between">
        <Button variant="secondary" onClick={() => (step === 0 ? router.push("/projects") : setStep(step - 1))}>
          {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < 2 ? (
          <Button onClick={next}>Next</Button>
        ) : (
          <Button onClick={create} disabled={busy}>
            {busy ? "Creating…" : "Create project"}
          </Button>
        )}
      </div>
    </div>
  );
}
