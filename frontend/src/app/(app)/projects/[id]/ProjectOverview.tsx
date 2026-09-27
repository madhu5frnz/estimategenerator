"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Select, StatusBadge } from "@/components/ui";
import { api, ApiError, del, patch, type Project } from "@/lib/api";
import { indianDate, inr, STATUS_LABELS } from "@/lib/format";

import { checkStep, ProjectFields, type ProjectFormValues, toPayload } from "../ProjectFields";

const CAN_EDIT = new Set(["professional", "admin"]);

function toForm(p: Project): ProjectFormValues {
  return {
    name: p.name, project_type: p.project_type, work_category_id: p.work_category_id ?? "",
    estimated_value: p.estimated_value ?? "", description: p.description ?? "",
    location: p.location ?? "", district: p.district ?? "", state: p.state,
    client_department: p.client_department ?? "", engineer_name: p.engineer_name ?? "",
    contractor_name: p.contractor_name ?? "", reference_number: p.reference_number ?? "",
    project_date: p.project_date ?? "",
  };
}

export function ProjectOverview({ id }: { id: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProjectFormValues | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Project>(`/projects/${id}`)
      .then(setProject)
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : "Could not load the project."));
  }, [id]);

  if (loadError) return <Alert>{loadError}</Alert>;
  if (!project) return <p className="text-muted">Loading…</p>;
  const canEdit = CAN_EDIT.has(project.my_role);

  async function save(changes: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      const updated = await patch<Project>(`/projects/${id}`, changes);
      setProject(updated);
      setEditing(null);
      setErrors({});
    } catch (e) {
      if (e instanceof ApiError) {
        const fields = e.fieldErrors();
        if (Object.keys(fields).length) setErrors(fields);
        else setError(e.message);
      } else setError("Could not save.");
    } finally {
      setBusy(false);
    }
  }

  function submitEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const found = { ...checkStep(editing, 0), ...checkStep(editing, 1) };
    setErrors(found);
    if (!Object.keys(found).length) void save(toPayload(editing));
  }

  async function remove() {
    setBusy(true);
    try {
      await del(`/projects/${id}`);
      router.push("/projects");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete.");
      setBusy(false);
      setConfirmDelete(false);
    }
  }

  const details: [string, string][] = [
    ["Type", project.project_type_label],
    ["Estimated value", inr(project.estimated_value)],
    ["Location", project.location ?? "—"],
    ["District", project.district ?? "—"],
    ["State", project.state],
    ["Department / client", project.client_department ?? "—"],
    ["Engineer / consultant", project.engineer_name ?? "—"],
    ["Contractor", project.contractor_name ?? "—"],
    ["Reference number", project.reference_number ?? "—"],
    ["Date", indianDate(project.project_date)],
    ["Created", indianDate(project.created_at)],
    ["Last updated", indianDate(project.updated_at)],
  ];

  return (
    <div className="max-w-5xl space-y-5">
      <div className="text-xs">
        <Link href="/projects" className="text-accent hover:underline">
          Projects
        </Link>{" "}
        / {project.name}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{project.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <StatusBadge status={project.status} />
            <Badge>Your role: {project.my_role}</Badge>
          </div>
        </div>
        {canEdit && !editing ? (
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Change status"
              value={project.status}
              disabled={busy}
              onChange={(e) => void save({ status: e.target.value })}
              className="w-auto"
            >
              {Object.entries(STATUS_LABELS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </Select>
            <Button variant="secondary" onClick={() => setEditing(toForm(project))}>
              Edit details
            </Button>
            {project.my_role === "admin" ? (
              <Button variant="ghost" className="text-bad" onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      {error ? <Alert>{error}</Alert> : null}
      {confirmDelete ? (
        <Alert tone="warn">
          <p>
            Delete <strong>{project.name}</strong>? It will disappear from your project list.
          </p>
          <div className="mt-2 flex gap-2">
            <Button variant="danger" onClick={remove} disabled={busy}>
              Yes, delete
            </Button>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
          </div>
        </Alert>
      ) : null}

      {editing ? (
        <Card title="Edit project">
          <form onSubmit={submitEdit} className="space-y-4" noValidate>
            <ProjectFields values={editing} errors={errors} onChange={(c) => setEditing({ ...editing, ...c })} />
            <div className="flex gap-2">
              <Button type="submit" disabled={busy}>
                {busy ? "Saving…" : "Save changes"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      ) : (
        <Card title="Project details">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {details.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="num">{value}</dd>
              </div>
            ))}
          </dl>
          {project.description ? (
            <div className="mt-4">
              <div className="text-xs text-muted">Description</div>
              <p className="whitespace-pre-wrap">{project.description}</p>
            </div>
          ) : null}
        </Card>
      )}

      <Card title="Estimates">
        <p className="text-muted">
          Estimates, BOQ and versions for this project arrive in M3. Until then you can try the{" "}
          <Link href="/calculator" className="text-accent hover:underline">
            Quantity Calculator
          </Link>
          .
        </p>
      </Card>
    </div>
  );
}
