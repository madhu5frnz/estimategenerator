"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      await post("/auth/register", form, { redirectOn401: false });
      router.replace("/dashboard");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const fields = e.fieldErrors();
        setErrors(fields);
        if (!Object.keys(fields).length) setError(e.message);
      } else setError("Registration failed.");
      setBusy(false);
    }
  }

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Create your account</h1>
      <p className="text-xs text-muted">Free plan: 3 projects. No card needed.</p>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Full name" error={errors.full_name} required>
        <Input autoComplete="name" value={form.full_name} onChange={set("full_name")} aria-invalid={!!errors.full_name} />
      </Field>
      <Field label="Email" error={errors.email} required>
        <Input type="email" autoComplete="email" value={form.email} onChange={set("email")} aria-invalid={!!errors.email} />
      </Field>
      <Field label="Password" error={errors.password} hint="At least 8 characters." required>
        <Input
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          aria-invalid={!!errors.password}
        />
      </Field>
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Creating account…" : "Create account"}
      </Button>
      <p className="text-center text-xs">
        Already registered?{" "}
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
